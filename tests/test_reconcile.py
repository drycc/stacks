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
            ["success", "--stack", "nginx", "--version", "1.31.8", "--sha", "a" * 40],
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
            ])
        self.assertEqual(rc, 0)
        alert.assert_called_once_with(
            "nginx", "1.31.8", arch="amd64", flavour="debian-13",
            pipeline_url="https://ci/42",
        )

    def test_cli_alert_failure_returns_non_zero(self):
        with mock.patch("reconcile.alert_failure", side_effect=RuntimeError("github down")):
            rc = reconcile.main([
                "alert", "--stack", "nginx", "--version", "1.31.8",
                "--arch", "amd64", "--flavour", "debian-13",
            ])
        self.assertEqual(rc, 1)

    def test_cli_success_forwards_arguments(self):
        with mock.patch("reconcile.record_build", return_value="refs/tags/nginx@1.31.8") as tag, \
                mock.patch("reconcile.resolve_failures", return_value=[]) as resolve:
            rc = reconcile.main([
                "success", "--stack", "nginx", "--version", "1.31.8",
                "--sha", "a" * 40, "--arch", "amd64", "--flavour", "debian-13",
            ])
        self.assertEqual(rc, 0)
        tag.assert_called_once_with("nginx", "1.31.8", sha="a" * 40)
        resolve.assert_called_once_with(
            "nginx", "1.31.8", arch="amd64", flavour="debian-13",
        )

    def test_cli_success_returns_non_zero_when_reporting_fails(self):
        with mock.patch("reconcile.record_build", side_effect=RuntimeError("github down")), \
                mock.patch("reconcile.resolve_failures", side_effect=RuntimeError("github down")):
            rc = reconcile.main([
                "success", "--stack", "nginx", "--version", "1.31.8",
            ])
        self.assertEqual(rc, 1)

    def test_cli_success_still_resolves_after_tagging_fails(self):
        with mock.patch("reconcile.record_build", side_effect=RuntimeError("github down")), \
                mock.patch("reconcile.resolve_failures", return_value=[7]) as resolve:
            rc = reconcile.main([
                "success", "--stack", "nginx", "--version", "1.31.8",
            ])
        self.assertEqual(rc, 1)
        resolve.assert_called_once()


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
    """Serves GitHub search results, the recent-open-issues listing and
    tag-ref creation, recording every request as
    (method, url, params_or_json_body) tuples.

    search_items feed the /search endpoint (indexed issues); recent_items
    feed the /issues listing (fresh issues the search index has not
    ingested yet). ref_status/ref_payload control the /git/refs POST
    outcome (201 created, or 422 with a message)."""

    def __init__(self, search_items, created_number=555, recent_items=None,
                 ref_status=201, ref_payload=None):
        self.requests = []
        self._search = {"total_count": len(search_items), "items": search_items}
        self._recent = recent_items or []
        self._created_number = created_number
        self._ref_status = ref_status
        self._ref_payload = ref_payload if ref_payload is not None else {}

    def get(self, url, params=None, headers=None, **kwargs):
        self.requests.append(("GET", url, params))
        if url.endswith("/search/issues"):
            return FakeAlertResponse(self._search)
        if url.endswith("/repos/drycc/stacks/issues"):
            return FakeAlertResponse(self._recent)
        raise AssertionError("unexpected GET %s" % url)

    def post(self, url, json=None, headers=None, **kwargs):
        self.requests.append(("POST", url, json))
        if url.endswith("/issues"):
            return FakeAlertResponse({"number": self._created_number})
        if url.endswith("/git/refs"):
            return FakeAlertResponse(self._ref_payload, status=self._ref_status)
        return FakeAlertResponse({})

    def patch(self, url, json=None, headers=None, **kwargs):
        self.requests.append(("PATCH", url, json))
        return FakeAlertResponse({"state": "closed"})


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

    def test_alert_dedups_even_when_the_search_index_lags(self):
        # a freshly created issue is invisible to /search but present in
        # the recent-open-issues listing: dedup must not create a second one
        title = "build failed for nginx@1.31.8 on amd64/debian-13"
        session = AlertSession(search_items=[], recent_items=[{"number": 81, "title": title}])
        number = reconcile.alert_failure(
            "nginx", "1.31.8", arch="amd64", flavour="debian-13", session=session,
        )
        self.assertIsNone(number)
        self.assertEqual(
            [r for r in session.requests if r[0] == "POST"],
            [],
        )

    def test_alert_skips_when_an_issue_is_already_open(self):
        session = AlertSession(search_items=[{"number": 77, "title": "old"}])
        number = reconcile.alert_failure(
            "nginx", "1.31.8", arch="amd64", flavour="debian-13", session=session,
        )
        self.assertIsNone(number)
        self.assertEqual(
            [r for r in session.requests if r[0] == "POST"],
            [],
        )

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
        session = AlertSession(search_items=[{"number": 77}, {"number": 78}])
        closed = reconcile.resolve_failures(
            "nginx", "1.31.8", arch="amd64", flavour="debian-13", session=session,
        )
        self.assertEqual(closed, [77, 78])
        patches = [r for r in session.requests if r[0] == "PATCH"]
        self.assertEqual(
            sorted(p[1].rsplit("/", 1)[-1] for p in patches), ["77", "78"],
        )
        self.assertTrue(all(p[2] == {"state": "closed"} for p in patches))
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


class RecordBuildTest(unittest.TestCase):
    """record_build tags a successfully built item as a build record.

    The tag is purely informational - OSS objects stay the completion
    standard - and points at the commit that was checked out when the
    build ran. The nightly cron is the only build path, so tags never
    trigger anything.
    """

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

    def test_creates_the_stack_tag_pointing_at_the_build_commit(self):
        session = AlertSession(search_items=[])
        ref = reconcile.record_build("nginx", "1.31.8", sha="a" * 40, session=session)
        self.assertEqual(ref, "refs/tags/nginx@1.31.8")
        creations = [r for r in session.requests
                     if r[0] == "POST" and r[1].endswith("/repos/drycc/stacks/git/refs")]
        self.assertEqual(len(creations), 1)
        self.assertEqual(
            creations[0][2],
            {"ref": "refs/tags/nginx@1.31.8", "sha": "a" * 40},
        )

    def test_skips_when_the_other_arch_leg_tagged_first(self):
        # both matrix legs build the same item; whichever finishes first
        # creates the tag and the second one gets a 422 "already exists"
        session = AlertSession(
            search_items=[],
            ref_status=422,
            ref_payload={"message": "Reference already exists"},
        )
        ref = reconcile.record_build("nginx", "1.31.8", sha="a" * 40, session=session)
        self.assertIsNone(ref)

    def test_a_422_that_is_not_a_duplicate_is_an_error(self):
        session = AlertSession(
            search_items=[],
            ref_status=422,
            ref_payload={"message": "Invalid request"},
        )
        with self.assertRaises(RuntimeError):
            reconcile.record_build("nginx", "1.31.8", sha="a" * 40, session=session)

    def test_sha_defaults_to_ci_commit_sha(self):
        os.environ["CI_COMMIT_SHA"] = "b" * 40
        session = AlertSession(search_items=[])
        reconcile.record_build("nginx", "1.31.8", session=session)
        creation = [r for r in session.requests
                    if r[0] == "POST" and r[1].endswith("/git/refs")][0]
        self.assertEqual(creation[2]["sha"], "b" * 40)

    def test_without_token_makes_no_requests(self):
        os.environ.pop("GITHUB_TOKEN", None)
        session = AlertSession(search_items=[])
        ref = reconcile.record_build("nginx", "1.31.8", sha="a" * 40, session=session)
        self.assertIsNone(ref)
        self.assertEqual(session.requests, [])


class SuccessReportTest(unittest.TestCase):
    """cmd_success: record the build tag and close failure issues in one
    report call, tolerating either half failing."""

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

    def test_tags_the_item_and_closes_its_failure_issues(self):
        title = "build failed for nginx@1.31.8 on amd64/debian-13"
        session = AlertSession(search_items=[{"number": 77, "title": title}])
        with mock.patch("reconcile.requests", session):
            rc = reconcile.main([
                "success", "--stack", "nginx", "--version", "1.31.8",
                "--sha", "a" * 40, "--arch", "amd64", "--flavour", "debian-13",
            ])
        self.assertEqual(rc, 0)
        ref_posts = [r for r in session.requests
                     if r[0] == "POST" and r[1].endswith("/git/refs")]
        self.assertEqual(len(ref_posts), 1)
        self.assertEqual(ref_posts[0][2]["ref"], "refs/tags/nginx@1.31.8")
        patches = [r for r in session.requests if r[0] == "PATCH"]
        self.assertEqual(len(patches), 1)
        self.assertTrue(patches[0][1].endswith("/issues/77"))

    def test_a_duplicate_tag_still_closes_the_failure_issues(self):
        title = "build failed for nginx@1.31.8 on amd64/debian-13"
        session = AlertSession(
            search_items=[{"number": 77, "title": title}],
            ref_status=422,
            ref_payload={"message": "Reference already exists"},
        )
        with mock.patch("reconcile.requests", session):
            rc = reconcile.main([
                "success", "--stack", "nginx", "--version", "1.31.8",
                "--sha", "a" * 40, "--arch", "amd64", "--flavour", "debian-13",
            ])
        self.assertEqual(rc, 0)
        self.assertEqual(len([r for r in session.requests if r[0] == "PATCH"]), 1)


if __name__ == "__main__":
    unittest.main()
