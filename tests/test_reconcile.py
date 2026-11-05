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


if __name__ == "__main__":
    unittest.main()
