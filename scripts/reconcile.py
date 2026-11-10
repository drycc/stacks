"""OSS reconciliation: decide which stack versions still need building.

The OSS objects are the build-completion standard. This planner discovers
upstream release candidates (via checker.discover_candidates), compares them
against the objects that actually exist for the current arch and flavour,
and prints one stack@version item per line to stdout. Statistics go to
stderr. An upstream or OSS failure aborts the run instead of producing a
plan.

Only candidates newer than the newest version already stored in the SAME
series for the current stack/arch/flavour are eligible. A series is the
version with its final dot-separated component removed (13.4 -> 13,
8.0.1 -> 8.0). The newest N eligible candidates in each series form the
planning windows (checker.retention_keep). Older holes are never
backfilled, while a new release in an older maintained series can still
be built alongside a newer series. Missing versions inside an effective
window are still built, subject to the per-run caps.

The alert subcommand tracks a failed build as a deduplicated GitHub issue,
appending later failures for the same item as comments with bounded build-log
excerpts. The success subcommand records a successful build - a stack@version
tag pointing at the commit that built it, purely as a human-readable history
since the nightly cron is the only build path - and closes the open failure
issue. Tags record builds; they never trigger them.

Usage:
    python3 scripts/reconcile.py plan [--arch ARCH] [--flavour FLAVOUR]
        [--max-per-stack N] [--max-total N] [--retention N] [--stack NAME]
    python3 scripts/reconcile.py alert --stack NAME --version VERSION
        [--pipeline-url URL] [--log-file PATH] [--sha SHA]
        [--arch ARCH] [--flavour FLAVOUR]
    python3 scripts/reconcile.py success --stack NAME --version VERSION
        [--sha SHA] [--arch ARCH] [--flavour FLAVOUR]
"""

import argparse
import os
import platform
import re
import subprocess
import sys
from collections import deque

import checker
import requests
from packaging.version import InvalidVersion, parse


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


def _newest_existing_versions(existing, stack, arch, flavour):
    """Map each retention series to its newest parseable OSS version for
    this exact stack/arch/flavour.

    Existing-only versions matter: upstream discovery is a limited tag
    page, so the newest OSS object may not appear in the candidates.
    Unparseable versions are ignored here (and retained by the cleaner),
    since they cannot establish a semantic ordering boundary.
    """
    newest = {}
    for object_key in existing:
        parsed = checker.parse_object_key(object_key)
        if parsed is None:
            continue
        key_stack, version, key_arch, key_flavour = parsed
        if (key_stack, key_arch, key_flavour) != (stack, arch, flavour):
            continue
        try:
            parsed_version = parse(version)
        except InvalidVersion:
            continue
        series = checker.version_series(version)
        if series not in newest or parsed_version > newest[series]:
            newest[series] = parsed_version
    return newest


def build_plan(arch, flavour, stacks=None, discover=None, bucket=None,
               max_per_stack=1, max_total=10, retention=checker.DEFAULT_RETENTION):
    """Reconcile upstream candidates against OSS and pick what to build.

    Returns (chosen, deferred, dropped): chosen is a list of candidate
    dicts, newest first, capped at max_total with at most max_per_stack
    per stack; deferred counts the eligible missing versions left for
    later runs; dropped counts missing versions outside the effective
    planning window.

    The planner rolls forward within each version series: a candidate is
    eligible only when it is newer than the newest version already stored
    in that series for this exact stack/arch/flavour. A series with no
    existing object is eligible too. The newest N eligible candidates in
    each series form the retention windows (checker.retention_keep).
    Older holes are never backfilled, so versions deleted by the cleaner
    cannot be rebuilt - even when OSS contains versions upstream
    discovery did not return, or when the cleaner uses a different N.
    """
    if discover is None:
        discover = checker.discover_candidates
    if bucket is None:
        # Only OSS planning needs storage credentials. GitHub alert/success
        # reporting must also start when those credentials are absent.
        import storage
        bucket = storage.bucket
    if stacks is None:
        stacks = default_stacks()
    chosen = []
    deferred = 0
    dropped = 0
    for stack in stacks:
        candidates = discover(stack)
        if not candidates:
            continue
        existing = list_existing_keys(bucket, "stacks/%s/%s-" % (stack, stack))
        newest_existing = _newest_existing_versions(existing, stack, arch, flavour)
        eligible_by_series = {}
        for candidate in candidates:
            series = checker.version_series(candidate["version"])
            boundary = newest_existing.get(series)
            if boundary is None:
                eligible_by_series.setdefault(series, []).append(candidate)
                continue
            try:
                if parse(candidate["version"]) > boundary:
                    eligible_by_series.setdefault(series, []).append(candidate)
            except InvalidVersion:
                # retention_keep applies the same conservative rule:
                # unknown-age versions are not discarded by a guess.
                eligible_by_series.setdefault(series, []).append(candidate)
        kept = set()
        for eligible in eligible_by_series.values():
            kept.update(checker.retention_keep(
                [candidate["version"] for candidate in eligible], retention))
        missing = []
        for candidate in candidates:
            if object_key(stack, candidate["version"], arch, flavour) in existing:
                continue
            if candidate["version"] in kept:
                missing.append(candidate)
            else:
                dropped += 1
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
    return chosen, deferred, dropped


def cmd_plan(args):
    try:
        chosen, deferred, dropped = build_plan(
            arch=args.arch,
            flavour=args.flavour,
            stacks=args.stacks,
            max_per_stack=args.max_per_stack,
            max_total=args.max_total,
            retention=args.retention,
        )
    except Exception as exc:  # noqa: BLE001 - abort rather than mis-plan
        print("reconcile: planning failed: %s" % exc, file=sys.stderr)
        return 1
    for candidate in chosen:
        print("%s@%s" % (candidate["stack"], candidate["version"]))
    print(
        "reconcile: arch=%s flavour=%s, %d to build, %d deferred, %d outside retention"
        % (args.arch, args.flavour, len(chosen), deferred, dropped),
        file=sys.stderr,
    )
    return 0


def _github_headers():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return None
    return {"Authorization": "token %s" % token}


def failure_issue_title(stack, version, arch, flavour):
    """Title of the (deduplicated) issue tracking a failed build.

    One issue per stack@version AND arch: both matrix legs have their own
    pipeline, and one arch can be fixed while the other still fails.
    """
    return "build failed for %s@%s on %s/%s" % (stack, version, arch, flavour)


def find_open_failure_issues(title, session, headers):
    """Return the open issues whose title matches.

    Two sources are combined: the search endpoint covers any volume of
    history, and the recent-open-issues listing adds an exact-title match
    as a second opinion. Both take a few seconds to reflect a freshly
    created issue, so deduplication is reliable for callers more than
    seconds apart (nightly runs, retried pipelines) but not against
    sub-second concurrent duplicates. No realistic flow produces those:
    each item is planned once per run and the matrix legs alert under
    arch-specific titles.
    """
    response = session.get(
        "https://api.github.com/search/issues",
        params={"q": 'repo:drycc/stacks is:issue is:open in:title "%s"' % title},
        headers=headers,
    )
    response.raise_for_status()
    found = {
        issue["number"]: issue
        for issue in response.json().get("items", [])
        if "pull_request" not in issue and issue.get("title") == title
    }
    listing = session.get(
        "https://api.github.com/repos/drycc/stacks/issues",
        params={
            "state": "open",
            "sort": "created",
            "direction": "desc",
            "per_page": 100,
        },
        headers=headers,
    )
    listing.raise_for_status()
    for issue in listing.json():
        if "pull_request" not in issue and issue["title"] == title:
            found.setdefault(issue["number"], issue)
    return sorted(found.values(), key=lambda issue: issue["number"])


FAILURE_LOG_MAX_LINES = 200
FAILURE_LOG_MAX_CHARS = 48000
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _failure_log_excerpt(log_file):
    """Read a bounded, terminal-formatting-free excerpt for a GitHub body."""
    if not log_file:
        return None
    lines = deque(maxlen=FAILURE_LOG_MAX_LINES)
    truncated = False
    try:
        with open(log_file, encoding="utf-8", errors="replace") as source:
            while True:
                # Bound each read as well as the retained line count: compiler
                # output can be arbitrarily large or contain very long lines.
                line = source.readline(FAILURE_LOG_MAX_CHARS + 1)
                if not line:
                    break
                truncated = truncated or len(lines) == lines.maxlen
                lines.append(line)
    except OSError as exc:
        print("reconcile: alert: cannot read build log %s: %s" % (log_file, exc),
              file=sys.stderr)
        return None
    excerpt = ANSI_ESCAPE.sub("", "".join(lines))
    if len(excerpt) > FAILURE_LOG_MAX_CHARS:
        truncated = True
        excerpt = excerpt[-FAILURE_LOG_MAX_CHARS:]
    if truncated:
        excerpt = "[... earlier build log omitted ...]\n" + excerpt
    return excerpt or None


def _failure_body(stack, version, arch, flavour, pipeline_url, sha=None,
                  log_excerpt=None):
    lines = [
        "The nightly reconcile run failed to build this item.",
        "",
        "- stack: %s" % stack,
        "- version: %s" % version,
        "- arch/flavour: %s/%s" % (arch, flavour),
    ]
    if sha:
        lines.append("- commit: %s" % sha)
    if pipeline_url:
        lines.append("- pipeline: %s" % pipeline_url)
    lines += [
        "",
        "The item stays on the nightly plan until it builds successfully, so"
        " this failure will repeat until the underlying error is fixed."
        " This issue closes automatically once the build succeeds.",
    ]
    if log_excerpt:
        lines += [
            "",
            "## Build log excerpt",
            "",
            "```text",
            log_excerpt,
            "```",
        ]
    return "\n".join(lines)


def alert_failure(stack, version, arch=None, flavour=None, pipeline_url=None,
                  log_file=None, sha=None, session=None):
    """Create or comment on the issue for stack@version, deduplicated by title.

    Returns the new issue number, or None when an existing issue was updated
    or no GITHUB_TOKEN is available.
    """
    headers = _github_headers()
    if headers is None:
        print("reconcile: alert: GITHUB_TOKEN not set, skipping", file=sys.stderr)
        return None
    if session is None:
        session = requests
    arch = arch or detect_arch()
    flavour = flavour or detect_flavour()
    sha = sha or os.environ.get("CI_COMMIT_SHA")
    title = failure_issue_title(stack, version, arch, flavour)
    body = _failure_body(
        stack, version, arch, flavour, pipeline_url, sha=sha,
        log_excerpt=_failure_log_excerpt(log_file),
    )
    issues = find_open_failure_issues(title, session, headers)
    if issues:
        for issue in issues:
            response = session.post(
                "https://api.github.com/repos/drycc/stacks/issues/%d/comments"
                % issue["number"],
                json={"body": body},
                headers=headers,
            )
            response.raise_for_status()
        print(
            "reconcile: alert: commented on issue(s) %s (%s)"
            % (", ".join("#%d" % issue["number"] for issue in issues), title),
            file=sys.stderr,
        )
        return None
    response = session.post(
        "https://api.github.com/repos/drycc/stacks/issues",
        json={"title": title, "body": body},
        headers=headers,
    )
    response.raise_for_status()
    number = response.json()["number"]
    print("reconcile: alert: created issue #%d (%s)" % (number, title), file=sys.stderr)
    return number


def resolve_failures(stack, version, arch=None, flavour=None, session=None):
    """Close the open failure issues for stack@version after a build succeeds.

    Returns the list of closed issue numbers (empty when nothing is open or
    no GITHUB_TOKEN is available).
    """
    headers = _github_headers()
    if headers is None:
        print("reconcile: resolve: GITHUB_TOKEN not set, skipping", file=sys.stderr)
        return []
    if session is None:
        session = requests
    arch = arch or detect_arch()
    flavour = flavour or detect_flavour()
    title = failure_issue_title(stack, version, arch, flavour)
    closed = []
    for issue in find_open_failure_issues(title, session, headers):
        comment = session.post(
            "https://api.github.com/repos/drycc/stacks/issues/%d/comments"
            % issue["number"],
            json={
                "body": "Closing automatically: %s@%s on %s/%s built"
                " successfully in the nightly reconcile run."
                % (stack, version, arch, flavour),
            },
            headers=headers,
        )
        comment.raise_for_status()
        patched = session.patch(
            "https://api.github.com/repos/drycc/stacks/issues/%d" % issue["number"],
            json={"state": "closed"},
            headers=headers,
        )
        patched.raise_for_status()
        closed.append(issue["number"])
    if closed:
        print(
            "reconcile: resolve: closed issue(s) %s"
            % ", ".join("#%d" % number for number in closed),
            file=sys.stderr,
        )
    return closed


def _current_commit():
    """The commit to point build-record tags at: CI_COMMIT_SHA when running
    in a pipeline, git HEAD otherwise (the workspace is mounted into the
    reporting container)."""
    sha = os.environ.get("CI_COMMIT_SHA")
    if sha:
        return sha
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def record_build(stack, version, sha=None, session=None):
    """Create the stack@version tag recording a successfully built item.

    The tag is lightweight, points at the build-time commit, and is a
    record for humans: OSS objects remain the build-completion standard
    and tags trigger nothing. Both matrix legs build the same item, so
    whichever finishes first creates the tag and the other skips on the
    422 "Reference already exists". Returns the created ref, or None
    when the tag already exists or no GITHUB_TOKEN is available.
    """
    headers = _github_headers()
    if headers is None:
        print("reconcile: tag: GITHUB_TOKEN not set, skipping", file=sys.stderr)
        return None
    if session is None:
        session = requests
    ref = "refs/tags/%s@%s" % (stack, version)
    if sha is None:
        sha = _current_commit()
    response = session.post(
        "https://api.github.com/repos/drycc/stacks/git/refs",
        json={"ref": ref, "sha": sha},
        headers=headers,
    )
    if response.status_code == 422 and "already exists" in response.json().get("message", ""):
        print("reconcile: tag: %s already exists, skipping" % ref, file=sys.stderr)
        return None
    response.raise_for_status()
    print("reconcile: tag: created %s at %s" % (ref, sha[:12]), file=sys.stderr)
    return ref


def cmd_alert(args):
    try:
        alert_failure(
            args.stack, args.version,
            arch=args.arch, flavour=args.flavour,
            pipeline_url=args.pipeline_url, log_file=args.log_file, sha=args.sha,
        )
    except Exception as exc:  # noqa: BLE001 - reporting must not mask failures
        print("reconcile: alert failed: %s" % exc, file=sys.stderr)
        return 1
    return 0


def cmd_success(args):
    """Record a successful build: tag it and close its failure issues.

    Either half may fail without stopping the other; the command exits
    non-zero so the failure is visible in the logs, but build.sh treats
    all reporting failures as non-fatal anyway.
    """
    problems = []
    try:
        record_build(args.stack, args.version, sha=args.sha)
    except Exception as exc:  # noqa: BLE001 - reporting must not mask failures
        print("reconcile: tag failed: %s" % exc, file=sys.stderr)
        problems.append("tag")
    try:
        resolve_failures(args.stack, args.version, arch=args.arch, flavour=args.flavour)
    except Exception as exc:  # noqa: BLE001 - reporting must not mask failures
        print("reconcile: resolve failed: %s" % exc, file=sys.stderr)
        problems.append("resolve")
    return 1 if problems else 0


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
        "--retention", type=int, default=checker.DEFAULT_RETENTION,
        help="newest versions kept per stack, shared with cleaner.py"
             " (default: %d)" % checker.DEFAULT_RETENTION,
    )
    plan_parser.add_argument(
        "--stack", action="append", dest="stacks",
        help="limit planning to this stack (repeatable)",
    )
    alert_parser = subparsers.add_parser(
        "alert", help="create or comment on the deduplicated issue for a failed build"
    )
    alert_parser.add_argument("--stack", required=True)
    alert_parser.add_argument("--version", required=True)
    alert_parser.add_argument(
        "--pipeline-url", default=None, help="link to the failing pipeline"
    )
    alert_parser.add_argument(
        "--log-file", default=None, help="build log to excerpt into the issue or comment"
    )
    alert_parser.add_argument(
        "--sha", default=None, help="failing commit (default: CI_COMMIT_SHA)"
    )
    alert_parser.add_argument("--arch", default=None, help="default: detected")
    alert_parser.add_argument("--flavour", default=None, help="default: detected")
    success_parser = subparsers.add_parser(
        "success", help="record a successful build (tag it and close its failure issue)"
    )
    success_parser.add_argument("--stack", required=True)
    success_parser.add_argument("--version", required=True)
    success_parser.add_argument(
        "--sha", default=None,
        help="commit to point the tag at (default: CI_COMMIT_SHA or git HEAD)",
    )
    success_parser.add_argument("--arch", default=None, help="default: detected")
    success_parser.add_argument("--flavour", default=None, help="default: detected")
    args = parser.parse_args(argv)
    if args.command == "plan":
        if args.retention < 1:
            plan_parser.error("--retention must be at least 1")
        if args.arch is None:
            args.arch = detect_arch()
        if args.flavour is None:
            args.flavour = detect_flavour()
        return cmd_plan(args)
    if args.command == "alert":
        return cmd_alert(args)
    if args.command == "success":
        return cmd_success(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
