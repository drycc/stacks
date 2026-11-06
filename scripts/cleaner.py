#!/usr/bin/env python3
"""
OSS stack cleaner: keep only the newest N versions of each stack.

Old binaries are never used by the Docker builds, which only reference
the current versions. The nightly reconcile planner rolls forward from
the newest OSS version and never backfills older holes, so versions
pruned by this cleaner are not planned again - even when the planner
and cleaner use different N values. checker.retention_keep provides the
shared semantic version ordering.

    python cleaner.py oss-stacks -n 3 [--dry-run] [--confirm]
    python cleaner.py oss-stacks -n 3 \
        --skip-stack go,java,node,php,python,ruby,rust --dry-run

  -n N: per (stack, arch, flavour) group, keep the newest N versions by
        semantic order and delete the older ones. Required.
  --skip-stack NAME: exclude a stack (repeatable, or comma-separated),
        e.g. preserve the full history of the language runtimes.

Version-pointer symlinks (go-1.24 -> go-1.24.5 style) are never deleted,
but -n may delete their targets, leaving the pointers to 404. Exclude
stacks whose pointers and full version history must stay intact (the
language runtimes listed above) with --skip-stack.
"""

import argparse
import os
import sys

import oss2
from packaging.version import parse as parse_version

import checker

BUCKET_NAME = 'drycc'


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


def retention_groups(objects, skip_stacks=()):
    """Group real (non-symlink) stack objects for retention cleanup.

    objects: an iterable of (key, type) pairs. Returns (groups, skipped):
    groups maps (stack, arch, flavour) -> {version: key}; skipped counts
    the symlinks and the keys that do not follow the artifact layout -
    neither is ever deleted by -n. Stacks named in skip_stacks are
    excluded entirely.
    """
    skip = frozenset(skip_stacks)
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
        if stack in skip:
            continue
        groups.setdefault((stack, arch, flavour), {})[version] = key
    return groups, skipped


def retention_prune(groups, count):
    """Plan the retention prune.

    Returns (victims, lines): victims is the flat list of keys to delete
    to bring every group within its newest `count` versions, and lines
    holds one human-readable summary line per group that loses
    versions. checker.retention_keep decides what stays (semantic order,
    unparseable versions always kept). Every victim is older than the
    group's newest retained version, and the nightly planner only rolls
    forward from that boundary, so victims are never rebuilt.
    """
    victims = []
    lines = []
    for (stack, arch, flavour), versions in sorted(groups.items()):
        retained = checker.retention_keep(list(versions), count)
        doomed = sorted(
            (version for version in versions if version not in retained),
            key=parse_version,  # oldest first; every doomed version is parseable
        )
        if not doomed:
            continue
        lines.append(
            "  %s linux-%s-%s: keeping %d of %d versions, deleting %s"
            % (stack, arch, flavour, len(retained), len(versions),
               ", ".join(doomed))
        )
        victims.extend(versions[version] for version in doomed)
    return victims, lines


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


def clean_oss_stacks(args):
    """Delete versions outside the newest-N retention window."""
    try:
        bucket = _oss_bucket()
    except Exception as exc:
        print(f"Error initializing OSS bucket: {exc}")
        return 1

    groups, skipped = retention_groups(
        iter_stack_objects(bucket), skip_stacks=args.skip_stacks)
    keys, detail = retention_prune(groups, args.keep_count)
    header = (f"Retention: keep the newest {args.keep_count} version(s) per"
              f" stack/arch/flavour, {len(keys)} object(s) beyond it")
    if skipped["symlinks"]:
        header += f", skipping {skipped['symlinks']} symlink(s)"
    if skipped["unparsed"]:
        header += f", skipping {skipped['unparsed']} unparsable key(s)"
    if args.skip_stacks:
        header += ", excluding stack(s): %s" % ",".join(args.skip_stacks)
    if not keys:
        print(header)
        print("Nothing to delete: every group is within the retention count.")
        return 0

    print(header)
    for line in detail:
        print(line)

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
  python cleaner.py oss-stacks -n 3                                     # Keep the newest 3 versions per stack/arch/flavour
  python cleaner.py oss-stacks -n 3 --dry-run                           # Preview the retention prune
  python cleaner.py oss-stacks -n 3 --skip-stack go,java,node,php,python,ruby,rust
                                                                        # Prune everything except the language runtimes

The nightly reconcile planner shares checker.retention_keep, so versions
pruned outside the retention window are not planned again. Symlinks are
never deleted; use --skip-stack for stacks whose version pointers and
full history must remain intact.
        """
    )
    subparsers = parser.add_subparsers(dest='action', help='Cleanup action to perform')

    oss_parser = subparsers.add_parser(
        'oss-stacks', help='Delete OSS stack versions beyond the newest N')
    oss_parser.add_argument(
        '-n', '--keep-count', type=int, required=True,
        help='keep the newest N versions per stack/arch/flavour and delete the older ones')
    oss_parser.add_argument(
        '--skip-stack', action='append', dest='skip_stacks', default=[],
        help='stack to exclude, named by its OSS directory'
             ' (repeatable, or comma-separated: go,java,node)')
    oss_parser.add_argument('--dry-run', action='store_true',
                            help='Only list the matching objects without deleting them')
    oss_parser.add_argument('--confirm', action='store_true',
                            help='Skip the confirmation prompt')

    args = parser.parse_args(argv)

    if not args.action:
        parser.print_help()
        return 1

    if args.action == 'oss-stacks':
        args.skip_stacks = [
            name for chunk in args.skip_stacks for name in chunk.split(",") if name
        ]
        if args.keep_count < 1:
            oss_parser.error("--keep-count must be at least 1")
        return clean_oss_stacks(args)
    parser.error(f"Unknown action: {args.action}")


if __name__ == '__main__':
    sys.exit(main())
