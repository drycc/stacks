#!/usr/bin/env python3
"""
OSS stack cleaner: keep only the newest N versions of each stack, with
an explicit retention list for objects that must never be deleted.

The nightly reconcile planner rolls forward from the newest OSS version
and never backfills older holes, so pruned versions are not planned
again. checker.retention_keep provides the shared semantic ordering.

    python cleaner.py oss-stacks -n 3 [--retention-list PATH] [--dry-run] [--confirm]

The default retention list is retention-list.txt in the repository root.
Its format is one entry per line; blank lines and # comments are ignored:

    # protect every version of this stack
    python
    # protect exactly this version on every arch/flavour
    valkey==3.15

Versions are exact OSS version strings, not prefixes or ranges: 3.15
does not match 3.15.0. Use == to pin a version; a single = is an error.
Bare stacks are excluded before retention ranking. Exact pins are then
applied as a final veto to the prune list, without changing the ranking,
so an old pinned version may keep a group above N objects.

Version-pointer symlinks are never deleted. Use bare stack entries for
runtimes such as go/java/node/php/python/ruby/rust when their pointer
targets and full history must remain intact.
"""

import argparse
import os
import re
import sys

import oss2
from packaging.version import parse as parse_version

import checker

BUCKET_NAME = 'drycc'
DEFAULT_RETENTION_LIST = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "retention-list.txt"))
STACK_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def parse_retention_list(lines):
    """Parse retention list lines into (whole_stacks, exact_version_pins).

    Both results are sets; exact_version_pins contains (stack, version)
    tuples. A single '=' is deliberately rejected so the file has one
    unambiguous spelling for a pinned version. Errors include the line
    number and abort the cleaner before it contacts OSS.
    """
    stacks = set()
    versions = set()
    for lineno, raw in enumerate(lines, 1):
        entry = raw.strip()
        if not entry or entry.startswith("#"):
            continue
        if "==" in entry:
            parts = entry.split("==")
            if len(parts) != 2:
                raise ValueError(
                    "retention list line %d: expected exactly one '==' separator" % lineno)
            stack, version = (part.strip() for part in parts)
            if not version or any(char.isspace() for char in version) or "=" in version:
                raise ValueError("retention list line %d: invalid version" % lineno)
        else:
            if "=" in entry:
                raise ValueError(
                    "retention list line %d: use == to pin a version" % lineno)
            stack, version = entry, None
        if not STACK_NAME.fullmatch(stack):
            raise ValueError("retention list line %d: invalid stack name" % lineno)
        if version is None:
            stacks.add(stack)
        else:
            versions.add((stack, version))
    return stacks, versions


def load_retention_list(path):
    """Load a retention list file, raising OSError/ValueError on any problem."""
    with open(path, encoding="utf-8") as f:
        return parse_retention_list(f)


def _oss_bucket():
    return oss2.Bucket(
        oss2.Auth(
            os.environ.get("OSS_ACCESS_KEY_ID"),
            os.environ.get("OSS_ACCESS_KEY_SECRET"),
        ),
        os.environ.get("OSS_ENDPOINT", "http://oss-accelerate.aliyuncs.com"),
        BUCKET_NAME,
    )


def iter_stack_objects(bucket, iterate=None):
    """Yield (key, type) for every object under stacks/."""
    if iterate is None:
        iterate = oss2.ObjectIterator
    for obj in iterate(bucket, prefix='stacks/'):
        yield obj.key, obj.type


def retention_groups(objects, protected_stacks=()):
    """Group real (non-symlink) stack objects for retention cleanup.

    objects: an iterable of (key, type) pairs. Returns (groups, skipped):
    groups maps (stack, arch, flavour) -> {version: key}; skipped counts
    the symlinks and the keys that do not follow the artifact layout -
    neither is ever deleted by -n. protected_stacks are excluded
    entirely by bare retention list entries.
    """
    protected_stacks = frozenset(protected_stacks)
    groups = {}
    skipped = {"symlinks": 0, "unparsed": 0}
    for key, type_ in objects:
        if type_ == "Symlink":
            skipped["symlinks"] += 1
            continue
        parsed = checker.parse_object_key(key)
        if parsed is None:
            skipped["unparsed"] += 1
            continue
        stack, version, arch, flavour = parsed
        if stack in protected_stacks:
            continue
        groups.setdefault((stack, arch, flavour), {})[version] = key
    return groups, skipped


def retention_prune(groups, count, protected_versions=()):
    """Plan the retention prune with exact-version retention list vetoes.

    Returns (victims, lines, protected): victims is the flat list of keys
    to delete, protected contains the pinned objects removed from that
    list, and lines accurately describes both outcomes. Bare stacks are
    excluded earlier by retention_groups. Exact pins are applied only
    after ranking, so they never change which unprotected versions are
    newest. Every victim is older than its group's newest retained
    version, and the nightly planner only rolls forward from that
    boundary, so victims are never rebuilt.
    """
    protected_versions = frozenset(protected_versions)
    victims = []
    lines = []
    protected = []
    for (stack, arch, flavour), versions in sorted(groups.items()):
        retained = checker.retention_keep(list(versions), count)
        doomed = sorted(
            (version for version in versions if version not in retained),
            key=parse_version,  # oldest first; every doomed version is parseable
        )
        pinned = [version for version in doomed
                  if (stack, version) in protected_versions]
        doomed = [version for version in doomed if version not in pinned]
        protected.extend(versions[version] for version in pinned)
        if doomed:
            lines.append(
                "  %s linux-%s-%s: keeping %d of %d versions, deleting %s"
                % (stack, arch, flavour, len(retained) + len(pinned),
                   len(versions), ", ".join(doomed))
            )
            victims.extend(versions[version] for version in doomed)
        if pinned:
            lines.append(
                "  %s linux-%s-%s: retention list protecting %s"
                % (stack, arch, flavour, ", ".join(pinned))
            )
    return victims, lines, protected


def delete_objects(bucket, keys, dry_run=False):
    """Delete each key; returns the number of successful deletions."""
    deleted = 0
    for key in keys:
        try:
            if dry_run:
                print(f"[DRY RUN] Would delete: {key}")
            else:
                bucket.delete_object(key)
                print(f"Deleted: {key}")
            deleted += 1
        except Exception as exc:
            print(f"Error deleting {key}: {exc}", file=sys.stderr)
    return deleted


def clean_oss_stacks(args, retention_list_stacks, retention_list_versions):
    """Delete versions outside the newest-N retention window, except
    objects protected by the already-loaded retention list."""
    try:
        bucket = _oss_bucket()
    except Exception as exc:
        print(f"Error initializing OSS bucket: {exc}")
        return 1

    groups, skipped = retention_groups(
        iter_stack_objects(bucket), protected_stacks=retention_list_stacks)
    keys, detail, protected = retention_prune(
        groups, args.keep_count, retention_list_versions)
    header = (f"Retention: keep the newest {args.keep_count} version(s) per"
              f" stack/arch/flavour, {len(keys)} object(s) scheduled for deletion")
    if skipped["symlinks"]:
        header += f", skipping {skipped['symlinks']} symlink(s)"
    if skipped["unparsed"]:
        header += f", skipping {skipped['unparsed']} unparsable key(s)"
    header += (", retention list: %d stack rule(s), %d version pin(s),"
               " %d protected object(s)"
               % (len(retention_list_stacks), len(retention_list_versions), len(protected)))
    print(header)
    for line in detail:
        print(line)
    if not keys:
        if protected:
            print("Nothing to delete: all versions beyond retention are"
                  " protected by the retention list.")
        else:
            print("Nothing to delete: every group is within the retention count.")
        return 0

    if not args.dry_run and not args.confirm:
        response = input(f"\nDelete these {len(keys)} objects? (y/N): ")
        if response.lower() != 'y':
            print("Aborted by user")
            return 0

    deleted = delete_objects(bucket, sorted(keys), args.dry_run)
    print(f"\nCompleted: {deleted}/{len(keys)} objects processed")
    return 0 if deleted == len(keys) else 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='OSS stack cleaner: keep the newest N versions per stack',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cleaner.py oss-stacks -n 3 --dry-run                           # Preview with the default retention list
  python cleaner.py oss-stacks -n 3 --retention-list /path/to/retention-list.txt  # Use an explicit retention list
  python cleaner.py oss-stacks -n 3 --confirm                           # Prune without a confirmation prompt

Retention list entries are 'python' (protect the whole stack) or
'valkey==3.15' (protect exactly that version). A single '=' is invalid.
Missing or malformed retention list files abort before OSS is contacted.
        """
    )
    subparsers = parser.add_subparsers(dest='action', help='Cleanup action to perform')

    oss_parser = subparsers.add_parser(
        'oss-stacks', help='Delete OSS stack versions beyond the newest N')
    oss_parser.add_argument(
        '-n', '--keep-count', type=int, required=True,
        help='keep the newest N versions per stack/arch/flavour and delete the older ones')
    oss_parser.add_argument(
        '--retention-list', default=DEFAULT_RETENTION_LIST,
        help='retention list file (default: retention-list.txt in the repository root)')
    oss_parser.add_argument('--dry-run', action='store_true',
                            help='Only list the matching objects without deleting them')
    oss_parser.add_argument('--confirm', action='store_true',
                            help='Skip the confirmation prompt')

    args = parser.parse_args(argv)

    if not args.action:
        parser.print_help()
        return 1

    if args.action == 'oss-stacks':
        if args.keep_count < 1:
            oss_parser.error("--keep-count must be at least 1")
        try:
            retention_list_stacks, retention_list_versions = load_retention_list(args.retention_list)
        except (OSError, ValueError) as exc:
            oss_parser.error(str(exc))
        return clean_oss_stacks(args, retention_list_stacks, retention_list_versions)
    parser.error(f"Unknown action: {args.action}")


if __name__ == '__main__':
    sys.exit(main())
