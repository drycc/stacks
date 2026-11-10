"""Planner tests for scripts/reconcile.py.

build_plan reconciles upstream release candidates against the OSS objects
that actually exist for the current arch and flavour, and returns the
stack@version items to build, newest first. The planner rolls forward
within each version series: only candidates newer than the newest object
in that series for the current stack/arch/flavour are eligible, and only
the newest N eligible candidates in each series are built. Older holes
are never backfilled, so cleaner victims cannot reappear on a later plan.
Missing versions inside an effective window are still built, subject to
the per-run caps.

ReconcileIssuesTest covers the daily failure-issue reconciliation: open
issues are paginated and filtered to exact managed titles; a stack whose
directory is gone is cancelled as not_planned without touching tags or
OSS, an existing stack closes only for an exact normal artifact, and
dry-run sends no comment or state change.

Run: .venv/bin/python -m unittest discover -s tests -p 'test_reconcile.py' -v
"""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from unittest import mock

# oss2.Auth requires credentials at import time; tests never talk to OSS
# (the bucket is replaced with a fake), so dummy values are enough.
os.environ.setdefault("OSS_ACCESS_KEY_ID", "test-access-key-id")
os.environ.setdefault("OSS_ACCESS_KEY_SECRET", "test-access-key-secret")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import checker  # noqa: E402
import cleaner  # noqa: E402
import reconcile  # noqa: E402
import storage  # noqa: E402


def candidate(stack, version, date=None):
    return {"stack": stack, "version": version, "upstream": "v" + version, "date": date}


def fake_discover(results):
    """Build a discover function serving fixed candidate lists per stack.

    Unconfigured stacks serve an empty list; every call is recorded.
    """

    def discover(stack):
        discover.calls.append(stack)
        return list(results.get(stack, []))

    discover.configured = sorted(results)
    discover.calls = []
    return discover


class FakeObject:
    def __init__(self, key, type="Normal"):
        self.key = key
        self.type = type


class FakeListResult:
    def __init__(self, objects, truncated=False, next_marker=""):
        self.object_list = objects
        self.is_truncated = truncated
        self.next_marker = next_marker


class FakeBucket:
    """Serves list_objects with optional pagination.

    entries: str key (Normal object) or (key, type) tuple.
    """

    def __init__(self, entries=(), page_size=1000):
        pairs = (e if isinstance(e, tuple) else (e, "Normal") for e in entries)
        self.entries = sorted(pairs, key=lambda pair: pair[0])
        self.page_size = page_size

    def list_objects(self, prefix="", marker="", max_keys=1000, **kwargs):
        matching = [
            (key, type)
            for key, type in self.entries
            if key.startswith(prefix) and key > marker
        ]
        page = matching[: self.page_size]
        return FakeListResult(
            [FakeObject(key, type) for key, type in page],
            len(matching) > len(page),
            page[-1][0] if page else "",
        )


class BrokenBucket:
    def list_objects(self, prefix="", **kwargs):
        raise RuntimeError("oss 500")


def key(stack, version, arch="amd64", flavour="debian-13"):
    return reconcile.object_key(stack, version, arch, flavour)


class ObjectKeyTest(unittest.TestCase):
    def test_matches_the_upload_layout(self):
        self.assertEqual(
            reconcile.object_key("nginx", "1.31.8", "amd64", "debian-13"),
            "stacks/nginx/nginx-1.31.8-linux-amd64-debian-13.tar.gz",
        )


class BuildPlanTest(unittest.TestCase):
    def plan(self, bucket, discover, arch="amd64", flavour="debian-13",
             stacks=None, max_per_stack=1, max_total=10,
             retention=checker.DEFAULT_RETENTION):
        return reconcile.build_plan(
            arch=arch,
            flavour=flavour,
            stacks=stacks or discover.configured,
            discover=discover,
            bucket=bucket,
            max_per_stack=max_per_stack,
            max_total=max_total,
            retention=retention,
        )

    def test_existing_version_is_skipped(self):
        bucket = FakeBucket([key("nginx", "1.31.8")])
        chosen, deferred, dropped = self.plan(
            bucket, fake_discover({"nginx": [candidate("nginx", "1.31.8")]}))
        self.assertEqual(chosen, [])
        self.assertEqual(deferred, 0)
        self.assertEqual(dropped, 0)

    def test_missing_version_for_current_arch_is_planned(self):
        bucket = FakeBucket([key("nginx", "1.31.8", arch="arm64")])
        chosen, deferred, dropped = self.plan(
            bucket, fake_discover({"nginx": [candidate("nginx", "1.31.8")]}))
        self.assertEqual(
            chosen,
            [{"stack": "nginx", "version": "1.31.8", "upstream": "v1.31.8", "date": None}],
        )
        self.assertEqual(dropped, 0)

    def test_other_arch_missing_does_not_trigger_rebuild(self):
        bucket = FakeBucket([key("nginx", "1.31.8", arch="amd64")])
        chosen, _, _ = self.plan(bucket, fake_discover({"nginx": [candidate("nginx", "1.31.8")]}))
        self.assertEqual(chosen, [])

    def test_other_flavour_does_not_count_as_built(self):
        bucket = FakeBucket([key("nginx", "1.31.8", flavour="debian-12")])
        chosen, _, _ = self.plan(bucket, fake_discover({"nginx": [candidate("nginx", "1.31.8")]}))
        self.assertEqual(len(chosen), 1)

    def test_symlink_objects_do_not_count_as_built(self):
        bucket = FakeBucket([(key("nginx", "1.31.8"), "Symlink")])
        chosen, _, _ = self.plan(bucket, fake_discover({"nginx": [candidate("nginx", "1.31.8")]}))
        self.assertEqual(len(chosen), 1)

    def test_limit_of_one_version_per_stack_keeps_newest(self):
        bucket = FakeBucket()
        discover = fake_discover(
            {"nginx": [
                candidate("nginx", "1.31.9", datetime(2026, 11, 4, tzinfo=timezone.utc)),
                candidate("nginx", "1.31.8", datetime(2026, 11, 3, tzinfo=timezone.utc)),
                candidate("nginx", "1.31.7", datetime(2026, 11, 2, tzinfo=timezone.utc)),
            ]}
        )
        chosen, deferred, dropped = self.plan(bucket, discover)
        self.assertEqual([c["version"] for c in chosen], ["1.31.9"])
        self.assertEqual(deferred, 1)
        self.assertEqual(dropped, 1)

    def test_global_order_newest_first_with_undated_last(self):
        bucket = FakeBucket()
        discover = fake_discover(
            {
                "nginx": [candidate("nginx", "1.31.8", datetime(2026, 10, 1, tzinfo=timezone.utc))],
                "rustfs": [candidate("rustfs", "1.0.4", datetime(2026, 11, 1, tzinfo=timezone.utc))],
                "java": [candidate("java", "21.0.5", None)],
            }
        )
        chosen, _, _ = self.plan(bucket, discover)
        self.assertEqual(
            [(c["stack"], c["version"]) for c in chosen],
            [("rustfs", "1.0.4"), ("nginx", "1.31.8"), ("java", "21.0.5")],
        )

    def test_max_total_limits_the_plan(self):
        bucket = FakeBucket()
        discover = fake_discover(
            {
                "nginx": [candidate("nginx", "1.31.9", datetime(2026, 11, 4, tzinfo=timezone.utc))],
                "rustfs": [candidate("rustfs", "1.0.5", datetime(2026, 11, 3, tzinfo=timezone.utc))],
                "java": [candidate("java", "21.0.5", datetime(2026, 11, 2, tzinfo=timezone.utc))],
            }
        )
        chosen, deferred, dropped = self.plan(bucket, discover, max_total=2)
        self.assertEqual(
            [(c["stack"], c["version"]) for c in chosen],
            [("nginx", "1.31.9"), ("rustfs", "1.0.5")],
        )
        self.assertEqual(deferred, 1)
        self.assertEqual(dropped, 0)

    def test_versions_outside_retention_are_never_planned(self):
        # old versions are not used by the Docker builds, so they are
        # outside the retention window and stay unbuilt - even when a
        # higher max-per-stack would have room for them
        bucket = FakeBucket()
        discover = fake_discover(
            {"nginx": [
                candidate("nginx", v, datetime(2026, 11, d, tzinfo=timezone.utc))
                for v, d in (("1.31.9", 9), ("1.31.8", 8), ("1.31.7", 7),
                             ("1.31.6", 6), ("1.31.5", 5))
            ]}
        )
        chosen, deferred, dropped = self.plan(bucket, discover, max_per_stack=10)
        self.assertEqual([c["version"] for c in chosen], ["1.31.9", "1.31.8"])
        self.assertEqual(deferred, 0)
        self.assertEqual(dropped, 3)

    def test_retention_uses_semantic_not_lexicographic_order(self):
        # lexicographic order would rank "1.31.9" above "1.31.10" and drop
        # the newest patch from the retention window instead of the old
        # 1.31.7; the planner and the cleaner must rank identically
        bucket = FakeBucket()
        discover = fake_discover(
            {"nginx": [
                candidate("nginx", v, datetime(2026, 11, d, tzinfo=timezone.utc))
                for v, d in (("1.31.10", 4), ("1.31.9", 3), ("1.31.8", 2), ("1.31.7", 1))
            ]}
        )
        chosen, deferred, dropped = self.plan(bucket, discover, max_per_stack=10, retention=3)
        self.assertEqual([c["version"] for c in chosen], ["1.31.10", "1.31.9", "1.31.8"])
        self.assertEqual(deferred, 0)
        self.assertEqual(dropped, 1)

    def test_holes_outside_retention_are_ignored(self):
        # the historical rustfs@1.0.3-style hole: a newer version exists,
        # the old one is outside the retention window and is never
        # backfilled - only the missing versions INSIDE the window build
        bucket = FakeBucket([key("rustfs", "1.0.4")])
        discover = fake_discover(
            {"rustfs": [
                candidate("rustfs", v, datetime(2026, 11, d, tzinfo=timezone.utc))
                for v, d in (("1.0.6", 6), ("1.0.5", 5), ("1.0.4", 4),
                             ("1.0.3", 3), ("1.0.2", 2))
            ]}
        )
        chosen, deferred, dropped = self.plan(bucket, discover)
        self.assertEqual([c["version"] for c in chosen], ["1.0.6"])
        self.assertEqual(deferred, 1)
        self.assertEqual(dropped, 2)

    def test_missing_versions_older_than_the_newest_existing_are_not_backfilled(self):
        # the planner rolls forward from what OSS already has: 1.0.4 is
        # inside the upstream retention window, but it is an old hole
        # next to the existing 1.0.5 and must not be built
        bucket = FakeBucket([key("rustfs", "1.0.5")])
        discover = fake_discover(
            {"rustfs": [
                candidate("rustfs", v, datetime(2026, 11, d, tzinfo=timezone.utc))
                for v, d in (("1.0.6", 6), ("1.0.5", 5), ("1.0.4", 4))
            ]}
        )
        chosen, deferred, dropped = self.plan(bucket, discover, max_per_stack=10)
        self.assertEqual([c["version"] for c in chosen], ["1.0.6"])
        self.assertEqual(deferred, 0)
        self.assertEqual(dropped, 1)

    def test_new_releases_in_older_series_are_not_blocked_by_a_newer_series(self):
        # mysql maintains both tracks: 7.18.2 must be compared with the
        # 7.18 series (empty here), not with the existing 8.0.0 object.
        bucket = FakeBucket([key("mysql", "8.0.0")])
        discover = fake_discover(
            {"mysql": [
                candidate("mysql", "8.0.1", datetime(2026, 11, 6, tzinfo=timezone.utc)),
                candidate("mysql", "7.18.2", datetime(2026, 11, 6, tzinfo=timezone.utc)),
            ]}
        )
        chosen, _, _ = self.plan(bucket, discover, max_per_stack=10)
        self.assertEqual(
            {candidate["version"] for candidate in chosen},
            {"7.18.2", "8.0.1"},
        )

    def test_roll_forward_boundary_is_per_series(self):
        bucket = FakeBucket([key("mysql", "8.0.1"), key("mysql", "7.18.1")])
        discover = fake_discover(
            {"mysql": [
                candidate("mysql", "8.0.2", datetime(2026, 11, 6, tzinfo=timezone.utc)),
                candidate("mysql", "8.0.0", datetime(2026, 11, 5, tzinfo=timezone.utc)),
                candidate("mysql", "7.18.2", datetime(2026, 11, 6, tzinfo=timezone.utc)),
                candidate("mysql", "7.18.0", datetime(2026, 11, 5, tzinfo=timezone.utc)),
            ]}
        )
        chosen, _, _ = self.plan(bucket, discover, max_per_stack=10)
        self.assertEqual(
            {candidate["version"] for candidate in chosen},
            {"7.18.2", "8.0.2"},
        )

    def test_oss_error_propagates(self):
        with self.assertRaises(RuntimeError):
            self.plan(BrokenBucket(), fake_discover({"nginx": [candidate("nginx", "1.31.8")]}))

    def test_discovery_error_propagates(self):
        def broken_discover(stack):
            raise RuntimeError("github down")

        with self.assertRaises(RuntimeError):
            self.plan(FakeBucket(), broken_discover, stacks=["nginx"])


class CleanerPlannerInteractionTest(unittest.TestCase):
    """Cross-tool contract: a version deleted by cleaner must never come
    back on the next nightly plan, even when OSS contains versions the
    upstream discovery did not return or the two N values differ."""

    def plan_after_prune(self, existing_versions, upstream_versions, cleaner_count):
        existing = [key("rustfs", version) for version in existing_versions]
        groups, _ = cleaner.retention_groups(
            [(object_key, "Normal") for object_key in existing])
        victims, _, _ = cleaner.retention_prune(groups, cleaner_count)
        bucket = FakeBucket(set(existing) - set(victims))
        discover = fake_discover(
            {"rustfs": [
                candidate("rustfs", version,
                          datetime(2026, 11, 10 - index, tzinfo=timezone.utc))
                for index, version in enumerate(upstream_versions)
            ]}
        )
        return reconcile.build_plan(
            arch="amd64", flavour="debian-13", stacks=["rustfs"],
            discover=discover, bucket=bucket, max_per_stack=10,
        )

    def test_existing_only_newer_version_prevents_victim_rebuild(self):
        # 1.0.6 exists on OSS but is absent from discovery (which only
        # returns a limited upstream tag page). Cleaner deletes 1.0.3;
        # the old planner would immediately rebuild it as an in-window
        # upstream candidate.
        chosen, _, _ = self.plan_after_prune(
            existing_versions=("1.0.6", "1.0.5", "1.0.4", "1.0.3"),
            upstream_versions=("1.0.5", "1.0.4", "1.0.3", "1.0.2"),
            cleaner_count=3,
        )
        self.assertEqual(chosen, [])

    def test_a_smaller_cleaner_count_does_not_cause_rebuilds(self):
        # cleaner -n 1 removes 1.0.2 and 1.0.1. The default planner
        # retention is 3, but rolling forward means neither deletion can
        # become a new build candidate.
        chosen, _, _ = self.plan_after_prune(
            existing_versions=("1.0.3", "1.0.2", "1.0.1"),
            upstream_versions=("1.0.3", "1.0.2", "1.0.1"),
            cleaner_count=1,
        )
        self.assertEqual(chosen, [])


class ListKeysTest(unittest.TestCase):
    def test_paginates_through_all_pages(self):
        entries = [key("nginx", v) for v in ("1.31.7", "1.31.8", "1.31.9")]
        bucket = FakeBucket(entries, page_size=1)
        keys = reconcile.list_existing_keys(bucket, "stacks/nginx/nginx-")
        self.assertEqual(
            keys,
            set(entries),
        )
        self.assertGreaterEqual(bucket.page_size and 3, 3)


class DetectionTest(unittest.TestCase):
    def test_detect_flavour_reads_os_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "os-release")
            with open(path, "w") as f:
                f.write('NAME="Ubuntu"\nID=ubuntu\nVERSION_ID="24.04"\n')
            self.assertEqual(reconcile.detect_flavour(path), "ubuntu-24.04")

    def test_detect_arch_maps_machine_names(self):
        for machine, arch in (("x86_64", "amd64"), ("aarch64", "arm64")):
            with mock.patch("reconcile.platform.machine", return_value=machine):
                self.assertEqual(reconcile.detect_arch(), arch)


class DefaultStacksTest(unittest.TestCase):
    def test_covers_real_stack_directories(self):
        stacks = reconcile.default_stacks()
        self.assertIn("nginx", stacks)
        for name in stacks:
            self.assertIn(name, checker.repo_info_table)


class CliTest(unittest.TestCase):
    def setUp(self):
        self._orig_bucket = storage.bucket
        self._orig_discover = checker.discover_candidates
        storage.bucket = FakeBucket()
        checker.discover_candidates = fake_discover({})

    def tearDown(self):
        storage.bucket = self._orig_bucket
        checker.discover_candidates = self._orig_discover

    def run_plan(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = reconcile.main(argv)
        return rc, stdout.getvalue(), stderr.getvalue()

    def test_prints_plan_lines_to_stdout_and_stats_to_stderr(self):
        checker.discover_candidates = fake_discover({"nginx": [candidate("nginx", "1.31.8")]})
        rc, stdout, stderr = self.run_plan(
            ["plan", "--arch", "amd64", "--flavour", "debian-13"]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(stdout, "nginx@1.31.8\n")
        self.assertIn("1 to build", stderr)

    def test_empty_plan_returns_zero_with_empty_stdout(self):
        rc, stdout, _ = self.run_plan(["plan", "--arch", "amd64", "--flavour", "debian-13"])
        self.assertEqual(rc, 0)
        self.assertEqual(stdout, "")

    def test_planning_failure_returns_non_zero_without_plan(self):
        def broken_discover(stack):
            raise RuntimeError("github down")

        checker.discover_candidates = broken_discover
        rc, stdout, stderr = self.run_plan(
            ["plan", "--arch", "amd64", "--flavour", "debian-13"]
        )
        self.assertEqual(rc, 1)
        self.assertEqual(stdout, "")
        self.assertIn("github down", stderr)

    def test_stack_filter_limits_discovery(self):
        served = fake_discover({"nginx": [candidate("nginx", "1.31.8")]})
        checker.discover_candidates = served
        self.run_plan(["plan", "--arch", "amd64", "--flavour", "debian-13", "--stack", "nginx"])
        self.assertEqual(served.calls, ["nginx"])

    def test_retention_flag_limits_the_plan_and_reports_the_dropped(self):
        checker.discover_candidates = fake_discover(
            {"nginx": [
                candidate("nginx", v, datetime(2026, 11, d, tzinfo=timezone.utc))
                for v, d in (("1.31.10", 4), ("1.31.9", 3), ("1.31.8", 2), ("1.31.7", 1))
            ]}
        )
        rc, stdout, stderr = self.run_plan(
            ["plan", "--arch", "amd64", "--flavour", "debian-13", "--retention", "3"]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(stdout, "nginx@1.31.10\n")
        self.assertIn("1 to build", stderr)
        self.assertIn("2 deferred", stderr)
        self.assertIn("1 outside retention", stderr)

    def test_retention_below_one_is_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            self.run_plan(["plan", "--retention", "0"])
        self.assertEqual(ctx.exception.code, 2)

    def test_reporting_commands_start_without_oss_credentials(self):
        script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "reconcile.py"
        )
        env = os.environ.copy()
        for name in (
            "OSS_ENDPOINT", "OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET", "GITHUB_TOKEN"
        ):
            env.pop(name, None)
        commands = (
            ["alert", "--stack", "nginx", "--version", "1.31.8"],
            ["request", "--stack", "nginx", "--version", "1.31.8", "--sha", "a" * 40],
            ["success", "--stack", "nginx", "--version", "1.31.8"],
            ["reconcile-issues"],
        )
        for command in commands:
            with self.subTest(command=command[0]):
                result = subprocess.run(
                    [sys.executable, script, *command],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("GITHUB_TOKEN not set, skipping", result.stderr)

    def test_cli_alert_forwards_arguments(self):
        with mock.patch("reconcile.alert_failure", return_value=42) as alert:
            rc = reconcile.main([
                "alert", "--stack", "nginx", "--version", "1.31.8",
                "--arch", "amd64", "--flavour", "debian-13",
                "--pipeline-url", "https://ci/42",
                "--log-file", "/tmp/nginx-build.log", "--sha", "a" * 40,
            ])
        self.assertEqual(rc, 0)
        alert.assert_called_once_with(
            "nginx", "1.31.8", arch="amd64", flavour="debian-13",
            pipeline_url="https://ci/42", log_file="/tmp/nginx-build.log",
            sha="a" * 40,
        )

    def test_cli_alert_failure_returns_non_zero(self):
        with mock.patch("reconcile.alert_failure", side_effect=RuntimeError("github down")):
            rc = reconcile.main([
                "alert", "--stack", "nginx", "--version", "1.31.8",
                "--arch", "amd64", "--flavour", "debian-13",
            ])
        self.assertEqual(rc, 1)

    def test_cli_success_forwards_arguments(self):
        with mock.patch("reconcile.resolve_failures", return_value=[]) as resolve:
            rc = reconcile.main([
                "success", "--stack", "nginx", "--version", "1.31.8",
                "--arch", "amd64", "--flavour", "debian-13",
            ])
        self.assertEqual(rc, 0)
        resolve.assert_called_once_with(
            "nginx", "1.31.8", arch="amd64", flavour="debian-13",
        )

    def test_cli_success_returns_non_zero_when_reporting_fails(self):
        with mock.patch("reconcile.resolve_failures", side_effect=RuntimeError("github down")):
            rc = reconcile.main([
                "success", "--stack", "nginx", "--version", "1.31.8",
            ])
        self.assertEqual(rc, 1)


class FakeAlertResponse:
    def __init__(self, payload=None, status=200):
        self._payload = payload or {}
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http %d" % self.status_code)


class AlertSession:
    """Serves GitHub issues and tag refs, recording every request as
    (method, url, params_or_json_body) tuples.

    search_items feed the /search endpoint (indexed issues); recent_items
    feed the /issues listing (fresh issues the search index has not
    ingested yet). ref_status/ref_payload control the /git/refs POST
    outcome (201 created, or 422 with a message). delete_status controls
    tag deletion. Every GitHub method requires the production timeout."""

    def __init__(self, search_items, created_number=555, recent_items=None,
                 ref_status=201, ref_payload=None, delete_status=204):
        self.requests = []
        self._search = {"total_count": len(search_items), "items": search_items}
        self._recent = recent_items or []
        self._created_number = created_number
        self._ref_status = ref_status
        self._ref_payload = ref_payload if ref_payload is not None else {}
        self._delete_status = delete_status

    @staticmethod
    def _check_timeout(timeout):
        if timeout != 30:
            raise AssertionError("GitHub request timeout must be 30, got %r" % timeout)

    def get(self, url, params=None, headers=None, timeout=None, **kwargs):
        self._check_timeout(timeout)
        self.requests.append(("GET", url, params))
        if url.endswith("/search/issues"):
            return FakeAlertResponse(self._search)
        if url.endswith("/repos/drycc/stacks/issues"):
            return FakeAlertResponse(self._recent)
        raise AssertionError("unexpected GET %s" % url)

    def post(self, url, json=None, headers=None, timeout=None, **kwargs):
        self._check_timeout(timeout)
        self.requests.append(("POST", url, json))
        if url.endswith("/issues"):
            return FakeAlertResponse({"number": self._created_number})
        if url.endswith("/git/refs"):
            return FakeAlertResponse(self._ref_payload, status=self._ref_status)
        return FakeAlertResponse({})

    def patch(self, url, json=None, headers=None, timeout=None, **kwargs):
        self._check_timeout(timeout)
        self.requests.append(("PATCH", url, json))
        return FakeAlertResponse({"state": "closed"})

    def delete(self, url, headers=None, timeout=None, **kwargs):
        self._check_timeout(timeout)
        self.requests.append(("DELETE", url, None))
        return FakeAlertResponse(status=self._delete_status)


class FailureIssueAlertTest(unittest.TestCase):
    def setUp(self):
        self._orig_token = os.environ.get("GITHUB_TOKEN")
        os.environ["GITHUB_TOKEN"] = "test-token"

    def tearDown(self):
        if self._orig_token is None:
            os.environ.pop("GITHUB_TOKEN", None)
        else:
            os.environ["GITHUB_TOKEN"] = self._orig_token

    def test_title_format(self):
        self.assertEqual(
            reconcile.failure_issue_title("postgresql", "14.21", "arm64", "debian-13"),
            "build failed for postgresql@14.21 on arm64/debian-13",
        )

    def test_alert_creates_deduplicated_issue_when_none_open(self):
        session = AlertSession(search_items=[])
        number = reconcile.alert_failure(
            "nginx", "1.31.8", arch="amd64", flavour="debian-13",
            pipeline_url="https://ci/42", session=session,
        )
        self.assertEqual(number, 555)
        searches = [r for r in session.requests
                    if r[0] == "GET" and r[1].endswith("/search/issues")]
        self.assertEqual(len(searches), 1)
        self.assertIn(
            '"build failed for nginx@1.31.8 on amd64/debian-13"',
            searches[0][2]["q"],
        )
        creations = [r for r in session.requests
                     if r[0] == "POST" and r[1].endswith("/repos/drycc/stacks/issues")]
        self.assertEqual(len(creations), 1)
        title = creations[0][2]["title"]
        body = creations[0][2]["body"]
        self.assertEqual(title, "build failed for nginx@1.31.8 on amd64/debian-13")
        self.assertIn("nginx", body)
        self.assertIn("1.31.8", body)
        self.assertIn("amd64/debian-13", body)
        self.assertIn("https://ci/42", body)
        self.assertIn("closes automatically", body)
        # tag-driven retries: nightly retry only while on the nightly plan
        self.assertIn("retries automatically only while the item"
                      " remains on the nightly plan", body)
        # manual outside-retention requests need an explicit tag re-push
        self.assertIn("re-push or recreate the nginx@1.31.8 tag", body)
        # the old perpetual-nightly-plan claim must be gone
        self.assertNotIn("stays on the nightly plan", body)

    def test_alert_dedups_even_when_the_search_index_lags(self):
        # a freshly created issue is invisible to /search but present in
        # the recent-open-issues listing: comment without creating a second one
        title = "build failed for nginx@1.31.8 on amd64/debian-13"
        session = AlertSession(search_items=[], recent_items=[{"number": 81, "title": title}])
        number = reconcile.alert_failure(
            "nginx", "1.31.8", arch="amd64", flavour="debian-13", session=session,
        )
        self.assertIsNone(number)
        self.assertEqual(
            [r for r in session.requests
             if r[0] == "POST" and r[1].endswith("/repos/drycc/stacks/issues")],
            [],
        )
        comments = [r for r in session.requests
                    if r[0] == "POST" and r[1].endswith("/issues/81/comments")]
        self.assertEqual(len(comments), 1)

    def test_alert_appends_a_failure_comment_when_an_issue_is_already_open(self):
        title = "build failed for nginx@1.31.8 on amd64/debian-13"
        session = AlertSession(search_items=[{"number": 77, "title": title}])
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as build_log:
            build_log.write("configure complete\nRuntimeError: compiler failed\n")
            build_log.flush()
            number = reconcile.alert_failure(
                "nginx", "1.31.8", arch="amd64", flavour="debian-13",
                pipeline_url="https://ci/43", log_file=build_log.name,
                sha="b" * 40, session=session,
            )
        self.assertIsNone(number)
        self.assertEqual(
            [r for r in session.requests
             if r[0] == "POST" and r[1].endswith("/repos/drycc/stacks/issues")],
            [],
        )
        comments = [r for r in session.requests
                    if r[0] == "POST" and r[1].endswith("/issues/77/comments")]
        self.assertEqual(len(comments), 1)
        body = comments[0][2]["body"]
        self.assertIn("https://ci/43", body)
        self.assertIn("b" * 40, body)
        self.assertIn("RuntimeError: compiler failed", body)

    def test_alert_without_token_makes_no_requests(self):
        os.environ.pop("GITHUB_TOKEN", None)
        session = AlertSession(search_items=[])
        number = reconcile.alert_failure(
            "nginx", "1.31.8", arch="amd64", flavour="debian-13", session=session,
        )
        self.assertIsNone(number)
        self.assertEqual(session.requests, [])

    def test_alert_omits_pipeline_line_without_url(self):
        session = AlertSession(search_items=[])
        reconcile.alert_failure(
            "nginx", "1.31.8", arch="amd64", flavour="debian-13", session=session,
        )
        creation = [r for r in session.requests
                    if r[0] == "POST" and r[1].endswith("/repos/drycc/stacks/issues")][0]
        self.assertNotIn("pipeline", creation[2]["body"])

    def test_alert_includes_commit_and_sanitized_build_log(self):
        session = AlertSession(search_items=[])
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as build_log:
            build_log.write("dependency installed\n\x1b[31mRuntimeError: build failed\x1b[0m\n")
            build_log.flush()
            reconcile.alert_failure(
                "nginx", "1.31.8", arch="amd64", flavour="debian-13",
                log_file=build_log.name, sha="a" * 40, session=session,
            )
        creation = [r for r in session.requests
                    if r[0] == "POST" and r[1].endswith("/repos/drycc/stacks/issues")][0]
        body = creation[2]["body"]
        self.assertIn("- commit: %s" % ("a" * 40), body)
        self.assertIn("Build log excerpt", body)
        self.assertIn("RuntimeError: build failed", body)
        self.assertNotIn("\x1b", body)

    def test_alert_log_excerpt_keeps_the_last_200_lines(self):
        session = AlertSession(search_items=[])
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as build_log:
            for line in range(1, 206):
                build_log.write("build-log-line-%03d\n" % line)
            build_log.flush()
            reconcile.alert_failure(
                "nginx", "1.31.8", arch="amd64", flavour="debian-13",
                log_file=build_log.name, session=session,
            )
        creation = [r for r in session.requests
                    if r[0] == "POST" and r[1].endswith("/repos/drycc/stacks/issues")][0]
        body = creation[2]["body"]
        self.assertNotIn("build-log-line-005", body)
        self.assertIn("build-log-line-006", body)
        self.assertIn("build-log-line-205", body)
        self.assertIn("earlier build log omitted", body)

    def test_alert_large_log_does_not_exceed_github_body_limit(self):
        session = AlertSession(search_items=[])
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as build_log:
            for _ in range(100):
                build_log.write("x" * 5000 + "\n")
            build_log.write("FINAL_BUILD_ERROR\n")
            build_log.flush()
            reconcile.alert_failure(
                "nginx", "1.31.8", arch="amd64", flavour="debian-13",
                log_file=build_log.name, session=session,
            )
        creation = [r for r in session.requests
                    if r[0] == "POST" and r[1].endswith("/repos/drycc/stacks/issues")][0]
        body = creation[2]["body"]
        self.assertLessEqual(len(body), 65536)
        self.assertIn("FINAL_BUILD_ERROR", body)
        self.assertIn("earlier build log omitted", body)

    def test_alert_ignores_search_results_with_a_different_title(self):
        session = AlertSession(search_items=[{
            "number": 77,
            "title": "build failed for nginx@1.31.7 on amd64/debian-13",
        }])
        number = reconcile.alert_failure(
            "nginx", "1.31.8", arch="amd64", flavour="debian-13", session=session,
        )
        self.assertEqual(number, 555)
        creations = [r for r in session.requests
                     if r[0] == "POST" and r[1].endswith("/repos/drycc/stacks/issues")]
        self.assertEqual(len(creations), 1)
        self.assertEqual(
            [r for r in session.requests if r[0] == "POST" and r[1].endswith("/comments")],
            [],
        )

    def test_alert_reads_large_logs_as_a_stream(self):
        session = AlertSession(search_items=[])
        log_open = mock.mock_open(read_data="first line\nFINAL_BUILD_ERROR\n")
        with mock.patch("builtins.open", log_open):
            reconcile.alert_failure(
                "nginx", "1.31.8", arch="amd64", flavour="debian-13",
                log_file="streamed-build.log", session=session,
            )
        handle = log_open()
        handle.read.assert_not_called()
        creation = [r for r in session.requests
                    if r[0] == "POST" and r[1].endswith("/repos/drycc/stacks/issues")][0]
        self.assertIn("FINAL_BUILD_ERROR", creation[2]["body"])

    def test_alert_missing_log_still_creates_an_issue(self):
        session = AlertSession(search_items=[])
        number = reconcile.alert_failure(
            "nginx", "1.31.8", arch="amd64", flavour="debian-13",
            log_file="/path/that/does/not/exist.log", session=session,
        )
        self.assertEqual(number, 555)
        creations = [r for r in session.requests
                     if r[0] == "POST" and r[1].endswith("/repos/drycc/stacks/issues")]
        self.assertEqual(len(creations), 1)


class FailureIssueResolveTest(unittest.TestCase):
    def setUp(self):
        self._orig_token = os.environ.get("GITHUB_TOKEN")
        os.environ["GITHUB_TOKEN"] = "test-token"

    def tearDown(self):
        if self._orig_token is None:
            os.environ.pop("GITHUB_TOKEN", None)
        else:
            os.environ["GITHUB_TOKEN"] = self._orig_token

    def test_closes_every_matching_issue_with_a_comment(self):
        title = "build failed for nginx@1.31.8 on amd64/debian-13"
        session = AlertSession(search_items=[
            {"number": 77, "title": title}, {"number": 78, "title": title},
        ])
        closed = reconcile.resolve_failures(
            "nginx", "1.31.8", arch="amd64", flavour="debian-13", session=session,
        )
        self.assertEqual(closed, [77, 78])
        patches = [r for r in session.requests if r[0] == "PATCH"]
        self.assertEqual(
            sorted(p[1].rsplit("/", 1)[-1] for p in patches), ["77", "78"],
        )
        self.assertTrue(all(
            p[2] == {"state": "closed", "state_reason": "completed"} for p in patches))
        comments = [r for r in session.requests
                    if r[0] == "POST" and r[1].endswith("/comments")]
        self.assertEqual(len(comments), 2)
        self.assertIn("built successfully", comments[0][2]["body"])

    def test_closes_freshly_created_issues_despite_index_lag(self):
        title = "build failed for nginx@1.31.8 on amd64/debian-13"
        session = AlertSession(search_items=[], recent_items=[{"number": 81, "title": title}])
        closed = reconcile.resolve_failures(
            "nginx", "1.31.8", arch="amd64", flavour="debian-13", session=session,
        )
        self.assertEqual(closed, [81])
        patches = [r for r in session.requests if r[0] == "PATCH"]
        self.assertEqual(len(patches), 1)
        self.assertTrue(patches[0][1].endswith("/issues/81"))

    def test_resolve_without_open_issues_is_a_noop(self):
        session = AlertSession(search_items=[])
        closed = reconcile.resolve_failures(
            "nginx", "1.31.8", arch="amd64", flavour="debian-13", session=session,
        )
        self.assertEqual(closed, [])
        self.assertEqual(
            [r for r in session.requests if r[0] in ("POST", "PATCH")],
            [],
        )

    def test_resolve_without_token_makes_no_requests(self):
        os.environ.pop("GITHUB_TOKEN", None)
        session = AlertSession(search_items=[])
        closed = reconcile.resolve_failures(
            "nginx", "1.31.8", arch="amd64", flavour="debian-13", session=session,
        )
        self.assertEqual(closed, [])
        self.assertEqual(session.requests, [])


class ReconcileIssuesSession:
    """Stateful GitHub issues endpoint for the daily reconciliation.

    Serves only state == "open" issues through numbered /issues pages at
    the production page size, records every request as
    (method, url, params_or_json_body) tuples, and applies PATCH state
    changes to the issue store. Every GitHub call must use the production
    timeout.
    """

    def __init__(self, issues=()):
        self.issues = [dict(issue) for issue in issues]
        self.requests = []

    @staticmethod
    def _check_timeout(timeout):
        if timeout != 30:
            raise AssertionError("GitHub request timeout must be 30, got %r" % timeout)

    def _open_issues(self):
        return [issue for issue in self.issues if issue.get("state", "open") == "open"]

    def get(self, url, params=None, headers=None, timeout=None, **kwargs):
        self._check_timeout(timeout)
        self.requests.append(("GET", url, params))
        if not url.endswith("/repos/drycc/stacks/issues"):
            raise AssertionError("unexpected GET %s" % url)
        if not params or params.get("per_page") != 100 or not params.get("page"):
            raise AssertionError("issue listing must use numbered 100-item pages")
        start = (params["page"] - 1) * params["per_page"]
        return FakeAlertResponse(self._open_issues()[start:start + params["per_page"]])

    def post(self, url, json=None, headers=None, timeout=None, **kwargs):
        self._check_timeout(timeout)
        self.requests.append(("POST", url, json))
        return FakeAlertResponse({})

    def patch(self, url, json=None, headers=None, timeout=None, **kwargs):
        self._check_timeout(timeout)
        self.requests.append(("PATCH", url, json))
        number = int(url.rsplit("/", 1)[-1])
        for issue in self.issues:
            if issue["number"] == number:
                issue["state"] = (json or {}).get("state", "open")
        return FakeAlertResponse({})

    def mutations(self):
        return [call for call in self.requests if call[0] in ("POST", "PATCH")]


class FailureIssueTitleParsingTest(unittest.TestCase):
    """Only exact managed failure titles may be reconciled."""

    def test_parses_the_managed_format(self):
        self.assertEqual(
            reconcile.parse_failure_issue_title(
                "build failed for nginx@1.31.8 on amd64/debian-13"),
            {"stack": "nginx", "version": "1.31.8", "arch": "amd64",
             "flavour": "debian-13"},
        )

    def test_rejects_every_non_managed_title(self):
        for title in (
            None,
            "",
            "update readme",
            "build failed for nginx@1.31.8 on amd64",
            "build failed for nginx@1.31.8 on amd64/debian-13 please look",
            "re: build failed for nginx@1.31.8 on amd64/debian-13",
            "Build failed for nginx@1.31.8 on amd64/debian-13",
        ):
            with self.subTest(title=title):
                self.assertIsNone(reconcile.parse_failure_issue_title(title))


class ReconcileIssuesTest(unittest.TestCase):
    """The daily pass closes what is provably done or impossible and
    leaves everything else open for a later retry."""

    def setUp(self):
        self._orig_token = os.environ.get("GITHUB_TOKEN")
        os.environ["GITHUB_TOKEN"] = "test-token"
        self.tmp = tempfile.TemporaryDirectory()
        os.mkdir(os.path.join(self.tmp.name, "nginx"))

    def tearDown(self):
        self.tmp.cleanup()
        if self._orig_token is None:
            os.environ.pop("GITHUB_TOKEN", None)
        else:
            os.environ["GITHUB_TOKEN"] = self._orig_token

    def managed(self, number, stack="nginx", version="1.31.8",
                arch="amd64", flavour="debian-13", **extra):
        issue = {
            "number": number,
            "title": reconcile.failure_issue_title(stack, version, arch, flavour),
            "state": "open",
        }
        issue.update(extra)
        return issue

    def run_pass(self, session, bucket=None, arch="amd64", **kwargs):
        return reconcile.reconcile_issues(
            arch=arch, session=session, bucket=bucket,
            stacks_dir=self.tmp.name, **kwargs)

    def test_paginates_open_issues_and_filters_prs_and_foreign_titles(self):
        # a full 100-item page of entries that must all be filtered (pull
        # requests carrying managed titles, then foreign titles), followed
        # by a short second page holding the two managed amd64 issues, an
        # other-arch issue and a closed issue that is never served
        issues = []
        for number in range(1, 51):
            issues.append(self.managed(
                number, pull_request={"url": "https://example.com/pr/%d" % number}))
        for number in range(51, 101):
            issues.append({
                "number": number, "title": "unrelated issue %d" % number,
                "state": "open",
            })
        issues.append(self.managed(101))
        issues.append(self.managed(102, version="1.31.7"))
        issues.append(self.managed(103, arch="arm64"))
        issues.append(self.managed(104, state="closed"))
        session = ReconcileIssuesSession(issues)
        counts = self.run_pass(session, bucket=FakeBucket())
        self.assertEqual(counts, {"closed": 0, "cancelled": 0, "skipped": 2})
        gets = [call for call in session.requests if call[0] == "GET"]
        self.assertEqual([call[2]["page"] for call in gets], [1, 2])
        self.assertTrue(all(call[2]["per_page"] == 100 for call in gets))
        self.assertEqual(session.mutations(), [])

    def test_exact_normal_artifact_closes_the_issue_as_completed(self):
        session = ReconcileIssuesSession([self.managed(77)])
        counts = self.run_pass(session, bucket=FakeBucket([key("nginx", "1.31.8")]))
        self.assertEqual(counts, {"closed": 1, "cancelled": 0, "skipped": 0})
        patches = [call for call in session.requests if call[0] == "PATCH"]
        self.assertEqual(len(patches), 1)
        self.assertTrue(patches[0][1].endswith("/issues/77"))
        self.assertEqual(
            patches[0][2], {"state": "closed", "state_reason": "completed"},
        )
        comments = [call for call in session.requests
                    if call[0] == "POST" and call[1].endswith("/issues/77/comments")]
        self.assertEqual(len(comments), 1)
        self.assertIn("built successfully", comments[0][2]["body"])
        # the explanation is posted before the state changes
        self.assertLess(
            session.requests.index(comments[0]),
            session.requests.index(patches[0]),
        )

    def test_repairs_a_failed_success_side_resolution(self):
        # the build succeeded and the artifact was uploaded, but the
        # success-side resolution failed earlier: the issue is still open
        # and the next daily pass must close it as completed
        session = ReconcileIssuesSession([self.managed(91)])
        counts = self.run_pass(session, bucket=FakeBucket([key("nginx", "1.31.8")]))
        self.assertEqual(counts, {"closed": 1, "cancelled": 0, "skipped": 0})
        patches = [call for call in session.requests if call[0] == "PATCH"]
        self.assertEqual([p[1].rsplit("/", 1)[-1] for p in patches], ["91"])
        self.assertEqual(
            patches[0][2], {"state": "closed", "state_reason": "completed"},
        )

    def test_missing_artifact_stays_open(self):
        session = ReconcileIssuesSession([self.managed(12)])
        counts = self.run_pass(session, bucket=FakeBucket())
        self.assertEqual(counts, {"closed": 0, "cancelled": 0, "skipped": 1})
        self.assertEqual(session.mutations(), [])

    def test_symlink_artifact_does_not_count_as_built(self):
        session = ReconcileIssuesSession([self.managed(13)])
        counts = self.run_pass(
            session, bucket=FakeBucket([(key("nginx", "1.31.8"), "Symlink")]))
        self.assertEqual(counts, {"closed": 0, "cancelled": 0, "skipped": 1})
        self.assertEqual(session.mutations(), [])

    def test_oss_error_keeps_the_issue_open_and_fails(self):
        session = ReconcileIssuesSession([self.managed(14)])
        with self.assertRaises(RuntimeError):
            self.run_pass(session, bucket=BrokenBucket())
        self.assertEqual(session.mutations(), [])
        self.assertTrue(any(call[0] == "GET" for call in session.requests))

    def test_removed_stack_cancels_every_matching_issue_without_oss_or_tags(self):
        # a stack whose directory is gone can never be built again: both
        # duplicates are cancelled as not_planned without consulting OSS
        # (BrokenBucket would raise on any OSS access) or request tags
        session = ReconcileIssuesSession([
            self.managed(21, stack="removed-stack", version="2.0.0"),
            self.managed(22, stack="removed-stack", version="2.0.0"),
        ])
        counts = self.run_pass(session, bucket=BrokenBucket())
        self.assertEqual(counts, {"closed": 0, "cancelled": 2, "skipped": 0})
        patches = [call for call in session.requests if call[0] == "PATCH"]
        self.assertEqual(
            sorted(p[1].rsplit("/", 1)[-1] for p in patches), ["21", "22"],
        )
        self.assertTrue(
            all(p[2] == {"state": "closed", "state_reason": "not_planned"}
                for p in patches),
        )
        comments = [call for call in session.requests
                    if call[0] == "POST" and call[1].endswith("/comments")]
        self.assertEqual(len(comments), 2)
        for call in comments:
            # distinct from the success-side resolution comment
            self.assertIn("no longer exists", call[2]["body"])
            self.assertIn("not planned", call[2]["body"])
            self.assertNotIn("built successfully", call[2]["body"])

    def test_absent_stacks_are_cancelled_before_an_oss_outage_aborts(self):
        # cancellation needs no OSS, so removed stacks are still handled
        # before the OSS uncertainty on the remaining issue fails the run
        session = ReconcileIssuesSession([
            self.managed(21, stack="removed-stack", version="2.0.0"),
            self.managed(22),
        ])
        with self.assertRaises(RuntimeError):
            self.run_pass(session, bucket=BrokenBucket())
        patches = [call for call in session.requests if call[0] == "PATCH"]
        self.assertEqual([p[1].rsplit("/", 1)[-1] for p in patches], ["21"])
        self.assertTrue(patches[0][2]["state_reason"] == "not_planned")

    def test_arch_filter_prevents_matrix_overlap(self):
        for arch in ("amd64", "arm64"):
            with self.subTest(arch=arch):
                session = ReconcileIssuesSession([
                    self.managed(31, arch="amd64"),
                    self.managed(32, arch="arm64"),
                ])
                counts = self.run_pass(
                    session, arch=arch,
                    bucket=FakeBucket([key("nginx", "1.31.8", arch=arch)]))
                self.assertEqual(counts, {"closed": 1, "cancelled": 0, "skipped": 0})
                patched = [call[1].rsplit("/", 1)[-1]
                           for call in session.requests if call[0] == "PATCH"]
                self.assertEqual(patched, ["31" if arch == "amd64" else "32"])

    def test_auto_arch_detects_the_running_arch(self):
        session = ReconcileIssuesSession([
            self.managed(61, arch="arm64"),
            self.managed(62, arch="amd64"),
        ])
        bucket = FakeBucket([key("nginx", "1.31.8", arch="arm64")])
        with mock.patch("reconcile.detect_arch", return_value="arm64"):
            counts = self.run_pass(session, bucket=bucket, arch="auto")
        self.assertEqual(counts, {"closed": 1, "cancelled": 0, "skipped": 0})
        patched = [call[1].rsplit("/", 1)[-1]
                   for call in session.requests if call[0] == "PATCH"]
        self.assertEqual(patched, ["61"])

    def test_dry_run_reports_without_comment_patch_or_state_change(self):
        session = ReconcileIssuesSession([
            self.managed(41),
            self.managed(42, stack="removed-stack", version="2.0.0"),
            self.managed(43, version="1.31.7"),
        ])
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            counts = self.run_pass(
                session, bucket=FakeBucket([key("nginx", "1.31.8")]), dry_run=True)
        self.assertEqual(counts, {"closed": 1, "cancelled": 1, "skipped": 1})
        self.assertEqual(session.mutations(), [])
        out = stdout.getvalue()
        self.assertIn("would close", out)
        self.assertIn("completed", out)
        self.assertIn("would cancel", out)
        self.assertIn("not_planned", out)
        self.assertNotIn("#43", out)

    def test_without_token_makes_no_requests(self):
        os.environ.pop("GITHUB_TOKEN", None)
        session = ReconcileIssuesSession([self.managed(51)])
        counts = self.run_pass(session, bucket=FakeBucket([key("nginx", "1.31.8")]))
        self.assertEqual(counts, {"closed": 0, "cancelled": 0, "skipped": 0})
        self.assertEqual(session.requests, [])

    def test_cli_reconcile_issues_forwards_arguments(self):
        with mock.patch(
            "reconcile.reconcile_issues",
            return_value={"closed": 1, "cancelled": 2, "skipped": 3},
        ) as daily_pass:
            rc = reconcile.main(["reconcile-issues", "--arch", "arm64", "--dry-run"])
        self.assertEqual(rc, 0)
        daily_pass.assert_called_once_with(arch="arm64", dry_run=True)

    def test_cli_reconcile_issues_defaults_to_auto_arch_and_real_run(self):
        with mock.patch(
            "reconcile.reconcile_issues",
            return_value={"closed": 0, "cancelled": 0, "skipped": 0},
        ) as daily_pass:
            rc = reconcile.main(["reconcile-issues"])
        self.assertEqual(rc, 0)
        daily_pass.assert_called_once_with(arch="auto", dry_run=False)

    def test_cli_reconcile_issues_failure_returns_non_zero(self):
        with mock.patch(
            "reconcile.reconcile_issues", side_effect=RuntimeError("oss down"),
        ):
            rc = reconcile.main(["reconcile-issues", "--arch", "amd64"])
        self.assertEqual(rc, 1)


class RequestBuildTest(unittest.TestCase):
    """Request tags start builds; abandoned requests delete those tags."""

    def setUp(self):
        self._orig_token = os.environ.get("GITHUB_TOKEN")
        os.environ["GITHUB_TOKEN"] = "test-token"
        self._orig_sha = os.environ.pop("CI_COMMIT_SHA", None)

    def tearDown(self):
        if self._orig_token is None:
            os.environ.pop("GITHUB_TOKEN", None)
        else:
            os.environ["GITHUB_TOKEN"] = self._orig_token
        if self._orig_sha is not None:
            os.environ["CI_COMMIT_SHA"] = self._orig_sha

    def test_creates_the_stack_tag_at_the_requested_commit(self):
        session = AlertSession(search_items=[])
        ref = reconcile.request_build("nginx", "1.31.8", sha="a" * 40, session=session)
        self.assertEqual(ref, "refs/tags/nginx@1.31.8")
        creations = [r for r in session.requests
                     if r[0] == "POST" and r[1].endswith("/repos/drycc/stacks/git/refs")]
        self.assertEqual(len(creations), 1)
        self.assertEqual(
            creations[0][2],
            {"ref": "refs/tags/nginx@1.31.8", "sha": "a" * 40},
        )

    def test_skips_when_the_other_arch_leg_requested_first(self):
        # Both matrix legs may request the same item; the second gets a
        # 422 "already exists" and must not try to recreate the ref.
        session = AlertSession(
            search_items=[],
            ref_status=422,
            ref_payload={"message": "Reference already exists"},
        )
        ref = reconcile.request_build("nginx", "1.31.8", sha="a" * 40, session=session)
        self.assertIsNone(ref)

    def test_a_422_that_is_not_a_duplicate_is_an_error(self):
        session = AlertSession(
            search_items=[],
            ref_status=422,
            ref_payload={"message": "Invalid request"},
        )
        with self.assertRaises(RuntimeError):
            reconcile.request_build("nginx", "1.31.8", sha="a" * 40, session=session)

    def test_sha_defaults_to_ci_commit_sha(self):
        os.environ["CI_COMMIT_SHA"] = "b" * 40
        session = AlertSession(search_items=[])
        reconcile.request_build("nginx", "1.31.8", session=session)
        creation = [r for r in session.requests
                    if r[0] == "POST" and r[1].endswith("/git/refs")][0]
        self.assertEqual(creation[2]["sha"], "b" * 40)

    def test_request_without_token_makes_no_requests(self):
        os.environ.pop("GITHUB_TOKEN", None)
        session = AlertSession(search_items=[])
        ref = reconcile.request_build("nginx", "1.31.8", sha="a" * 40, session=session)
        self.assertIsNone(ref)
        self.assertEqual(session.requests, [])

    def test_deletes_the_stack_tag(self):
        session = AlertSession(search_items=[])
        self.assertTrue(reconcile.delete_build_tag("nginx", "1.31.8", session=session))
        self.assertEqual(
            [r for r in session.requests if r[0] == "DELETE"],
            [("DELETE",
              "https://api.github.com/repos/drycc/stacks/git/refs/tags/nginx@1.31.8",
              None)],
        )

    def test_deleting_an_already_absent_tag_succeeds(self):
        session = AlertSession(search_items=[], delete_status=404)
        self.assertTrue(reconcile.delete_build_tag("nginx", "1.31.8", session=session))

    def test_an_unexpected_deletion_error_propagates(self):
        session = AlertSession(search_items=[], delete_status=500)
        with self.assertRaises(RuntimeError):
            reconcile.delete_build_tag("nginx", "1.31.8", session=session)

    def test_delete_without_token_makes_no_requests(self):
        os.environ.pop("GITHUB_TOKEN", None)
        session = AlertSession(search_items=[])
        self.assertFalse(reconcile.delete_build_tag("nginx", "1.31.8", session=session))
        self.assertEqual(session.requests, [])

    def test_cli_request_forwards_arguments(self):
        with mock.patch("reconcile.request_build", return_value="refs/tags/nginx@1.31.8") as request:
            rc = reconcile.main([
                "request", "--stack", "nginx", "--version", "1.31.8", "--sha", "a" * 40,
            ])
        self.assertEqual(rc, 0)
        request.assert_called_once_with("nginx", "1.31.8", sha="a" * 40)

    def test_cli_request_failure_returns_non_zero(self):
        with mock.patch("reconcile.request_build", side_effect=RuntimeError("github down")):
            rc = reconcile.main(["request", "--stack", "nginx", "--version", "1.31.8"])
        self.assertEqual(rc, 1)

    def test_cli_abandon_forwards_arguments(self):
        with mock.patch("reconcile.delete_build_tag", return_value=True) as delete:
            rc = reconcile.main(["abandon", "--stack", "nginx", "--version", "1.31.8"])
        self.assertEqual(rc, 0)
        delete.assert_called_once_with("nginx", "1.31.8")

    def test_cli_abandon_failure_returns_non_zero(self):
        with mock.patch("reconcile.delete_build_tag", side_effect=RuntimeError("github down")):
            rc = reconcile.main(["abandon", "--stack", "nginx", "--version", "1.31.8"])
        self.assertEqual(rc, 1)

    def test_cli_abandon_without_token_returns_non_zero(self):
        with mock.patch("reconcile.delete_build_tag", return_value=False):
            rc = reconcile.main(["abandon", "--stack", "nginx", "--version", "1.31.8"])
        self.assertEqual(rc, 1)


class SuccessReportTest(unittest.TestCase):
    """cmd_success only resolves failure issues; the request tag remains."""

    def setUp(self):
        self._orig_token = os.environ.get("GITHUB_TOKEN")
        os.environ["GITHUB_TOKEN"] = "test-token"
        self._orig_sha = os.environ.pop("CI_COMMIT_SHA", None)

    def tearDown(self):
        if self._orig_token is None:
            os.environ.pop("GITHUB_TOKEN", None)
        else:
            os.environ["GITHUB_TOKEN"] = self._orig_token
        if self._orig_sha is not None:
            os.environ["CI_COMMIT_SHA"] = self._orig_sha

    def test_closes_failure_issues_without_creating_a_ref(self):
        title = "build failed for nginx@1.31.8 on amd64/debian-13"
        session = AlertSession(search_items=[{"number": 77, "title": title}])
        with mock.patch("reconcile.requests", session):
            success_rc = reconcile.main([
                "success", "--stack", "nginx", "--version", "1.31.8",
                "--arch", "amd64", "--flavour", "debian-13",
            ])
        self.assertEqual(success_rc, 0)
        self.assertEqual([r for r in session.requests if r[1].endswith("/git/refs")], [])
        patches = [r for r in session.requests if r[0] == "PATCH"]
        self.assertEqual(len(patches), 1)
        self.assertTrue(patches[0][1].endswith("/issues/77"))

    def test_success_without_open_issues_makes_no_mutations(self):
        session = AlertSession(search_items=[])
        with mock.patch("reconcile.requests", session):
            success_rc = reconcile.main([
                "success", "--stack", "nginx", "--version", "1.31.8",
                "--arch", "amd64", "--flavour", "debian-13",
            ])
        self.assertEqual(success_rc, 0)
        self.assertEqual([r for r in session.requests if r[0] in ("POST", "PATCH", "DELETE")], [])


if __name__ == "__main__":
    unittest.main()
