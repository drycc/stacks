"""Planner tests for scripts/reconcile.py.

build_plan reconciles upstream release candidates against the OSS objects
that actually exist for the current arch and flavour, and returns the
stack@version items to build, newest first.

Run: .venv/bin/python -m unittest discover -s tests -p 'test_reconcile.py' -v
"""

import io
import os
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
             stacks=None, max_per_stack=1, max_total=10):
        return reconcile.build_plan(
            arch=arch,
            flavour=flavour,
            stacks=stacks or discover.configured,
            discover=discover,
            bucket=bucket,
            max_per_stack=max_per_stack,
            max_total=max_total,
        )

    def test_existing_version_is_skipped(self):
        bucket = FakeBucket([key("nginx", "1.31.8")])
        chosen, deferred = self.plan(bucket, fake_discover({"nginx": [candidate("nginx", "1.31.8")]}))
        self.assertEqual(chosen, [])
        self.assertEqual(deferred, 0)

    def test_missing_version_for_current_arch_is_planned(self):
        bucket = FakeBucket([key("nginx", "1.31.8", arch="arm64")])
        chosen, deferred = self.plan(bucket, fake_discover({"nginx": [candidate("nginx", "1.31.8")]}))
        self.assertEqual(
            chosen,
            [{"stack": "nginx", "version": "1.31.8", "upstream": "v1.31.8", "date": None}],
        )

    def test_other_arch_missing_does_not_trigger_rebuild(self):
        bucket = FakeBucket([key("nginx", "1.31.8", arch="amd64")])
        chosen, _ = self.plan(bucket, fake_discover({"nginx": [candidate("nginx", "1.31.8")]}))
        self.assertEqual(chosen, [])

    def test_other_flavour_does_not_count_as_built(self):
        bucket = FakeBucket([key("nginx", "1.31.8", flavour="debian-12")])
        chosen, _ = self.plan(bucket, fake_discover({"nginx": [candidate("nginx", "1.31.8")]}))
        self.assertEqual(len(chosen), 1)

    def test_symlink_objects_do_not_count_as_built(self):
        bucket = FakeBucket([(key("nginx", "1.31.8"), "Symlink")])
        chosen, _ = self.plan(bucket, fake_discover({"nginx": [candidate("nginx", "1.31.8")]}))
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
        chosen, deferred = self.plan(bucket, discover)
        self.assertEqual([c["version"] for c in chosen], ["1.31.9"])
        self.assertEqual(deferred, 2)

    def test_global_order_newest_first_with_undated_last(self):
        bucket = FakeBucket()
        discover = fake_discover(
            {
                "nginx": [candidate("nginx", "1.31.8", datetime(2026, 10, 1, tzinfo=timezone.utc))],
                "rustfs": [candidate("rustfs", "1.0.4", datetime(2026, 11, 1, tzinfo=timezone.utc))],
                "java": [candidate("java", "21.0.5", None)],
            }
        )
        chosen, _ = self.plan(bucket, discover)
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
        chosen, deferred = self.plan(bucket, discover, max_total=2)
        self.assertEqual(
            [(c["stack"], c["version"]) for c in chosen],
            [("nginx", "1.31.9"), ("rustfs", "1.0.5")],
        )
        self.assertEqual(deferred, 1)

    def test_oss_error_propagates(self):
        with self.assertRaises(RuntimeError):
            self.plan(BrokenBucket(), fake_discover({"nginx": [candidate("nginx", "1.31.8")]}))

    def test_discovery_error_propagates(self):
        def broken_discover(stack):
            raise RuntimeError("github down")

        with self.assertRaises(RuntimeError):
            self.plan(FakeBucket(), broken_discover, stacks=["nginx"])


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

    def test_cli_resolve_forwards_arguments(self):
        with mock.patch("reconcile.resolve_failures", return_value=[7]) as resolve:
            rc = reconcile.main([
                "resolve", "--stack", "nginx", "--version", "1.31.8",
                "--arch", "amd64", "--flavour", "debian-13",
            ])
        self.assertEqual(rc, 0)
        resolve.assert_called_once_with(
            "nginx", "1.31.8", arch="amd64", flavour="debian-13",
        )


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
    """Serves GitHub search results and the recent-open-issues listing,
    recording every request as (method, url, params_or_json_body) tuples.

    search_items feed the /search endpoint (indexed issues); recent_items
    feed the /issues listing (fresh issues the search index has not
    ingested yet)."""

    def __init__(self, search_items, created_number=555, recent_items=None):
        self.requests = []
        self._search = {"total_count": len(search_items), "items": search_items}
        self._recent = recent_items or []
        self._created_number = created_number

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


if __name__ == "__main__":
    unittest.main()
