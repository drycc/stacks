"""OSS reconciliation: decide which stack versions still need building.

The OSS objects are the build-completion standard. This planner discovers
upstream release candidates (via checker.discover_candidates), compares them
against the objects that actually exist for the current arch and flavour,
and prints one stack@version item per line to stdout. Statistics go to
stderr. It never creates tags or issues, and an upstream or OSS failure
aborts the run instead of producing a plan.

Usage:
    python3 scripts/reconcile.py plan [--arch ARCH] [--flavour FLAVOUR]
        [--max-per-stack N] [--max-total N] [--stack NAME]
"""

import argparse
import os
import platform
import sys

import checker
import storage


def object_key(stack, version, arch, flavour):
    """The OSS key a built stack version is uploaded to.

    Must stay in sync with the TARNAME layout produced by stack-utils
    (${STACK_NAME}-${STACK_VERSION}-${OS_NAME}-${OS_ARCH}-${OS_FLAVOUR}).
    """
    return "stacks/%s/%s-%s-linux-%s-%s.tar.gz" % (stack, stack, version, arch, flavour)


def detect_arch():
    machine = platform.machine()
    return {"x86_64": "amd64", "aarch64": "arm64"}.get(machine, machine)


def detect_flavour(path="/etc/os-release"):
    """Derive the flavour the same way stack-utils does (ID-VERSION_ID)."""
    fields = {}
    with open(path) as f:
        for line in f:
            if "=" in line:
                key, value = line.strip().split("=", 1)
                fields[key] = value.strip('"')
    return "%s-%s" % (fields["ID"], fields["VERSION_ID"])


def default_stacks():
    stacks_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "stacks")
    return sorted(
        name
        for name in os.listdir(stacks_dir)
        if os.path.isdir(os.path.join(stacks_dir, name))
        and name in checker.repo_info_table
    )


def list_existing_keys(bucket, prefix):
    """Return the set of normal (non-symlink) object keys under prefix.

    Symlinks (go-1.25 -> go-1.25.5 style pointers) must not count as built
    versions.
    """
    keys = set()
    marker = ""
    while True:
        result = bucket.list_objects(prefix=prefix, marker=marker, max_keys=1000)
        for obj in result.object_list:
            if obj.type != "Symlink":
                keys.add(obj.key)
        if not result.is_truncated:
            return keys
        marker = result.next_marker


def build_plan(arch, flavour, stacks=None, discover=None, bucket=None,
               max_per_stack=1, max_total=10):
    """Reconcile upstream candidates against OSS and pick what to build.

    Returns (chosen, deferred): chosen is a list of candidate dicts, newest
    first, capped at max_total with at most max_per_stack per stack; deferred
    counts the missing versions left for later runs.
    """
    if discover is None:
        discover = checker.discover_candidates
    if bucket is None:
        bucket = storage.bucket
    if stacks is None:
        stacks = default_stacks()
    chosen = []
    deferred = 0
    for stack in stacks:
        candidates = discover(stack)
        if not candidates:
            continue
        existing = list_existing_keys(bucket, "stacks/%s/%s-" % (stack, stack))
        missing = [
            candidate
            for candidate in candidates
            if object_key(stack, candidate["version"], arch, flavour) not in existing
        ]
        chosen.extend(missing[:max_per_stack])
        deferred += max(0, len(missing) - max_per_stack)
    chosen.sort(
        key=lambda candidate: (
            candidate["date"] is None,
            -candidate["date"].timestamp() if candidate["date"] else 0,
            candidate["stack"],
            candidate["version"],
        )
    )
    if len(chosen) > max_total:
        deferred += len(chosen) - max_total
        chosen = chosen[:max_total]
    return chosen, deferred


def cmd_plan(args):
    try:
        chosen, deferred = build_plan(
            arch=args.arch,
            flavour=args.flavour,
            stacks=args.stacks,
            max_per_stack=args.max_per_stack,
            max_total=args.max_total,
        )
    except Exception as exc:  # noqa: BLE001 - abort rather than mis-plan
        print("reconcile: planning failed: %s" % exc, file=sys.stderr)
        return 1
    for candidate in chosen:
        print("%s@%s" % (candidate["stack"], candidate["version"]))
    print(
        "reconcile: arch=%s flavour=%s, %d to build, %d deferred"
        % (args.arch, args.flavour, len(chosen), deferred),
        file=sys.stderr,
    )
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="reconcile.py",
        description="Plan stack builds from OSS reconciliation.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser(
        "plan", help="print stack@version items to build, one per line"
    )
    plan_parser.add_argument("--arch", default=None, help="target arch (default: detected)")
    plan_parser.add_argument(
        "--flavour", default=None, help="target flavour (default: /etc/os-release ID-VERSION_ID)"
    )
    plan_parser.add_argument(
        "--max-per-stack", type=int, default=1,
        help="max missing versions per stack per run (default: 1)",
    )
    plan_parser.add_argument(
        "--max-total", type=int, default=10,
        help="max items per run (default: 10)",
    )
    plan_parser.add_argument(
        "--stack", action="append", dest="stacks",
        help="limit planning to this stack (repeatable)",
    )
    args = parser.parse_args(argv)
    if args.command == "plan":
        if args.arch is None:
            args.arch = detect_arch()
        if args.flavour is None:
            args.flavour = detect_flavour()
        return cmd_plan(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
