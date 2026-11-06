"""Tests for scripts/cleaner.py.

The cleaner has one cleanup mode: per (stack, arch, flavour) group, keep
the newest N versions and delete the older ones. It shares the retention
rule with the nightly reconcile planner (checker.retention_keep), so
versions pruned outside the window are not planned again. --skip-stack
is an exclusion filter, not a second cleanup mode.

Version-pointer symlinks (go-1.24 -> go-1.24.5 style) are never deleted;
the tests pin that -n leaves them alone and that skipped stacks are
excluded completely.

Run: .venv/bin/python -m unittest discover -s tests -p 'test_cleaner.py' -v
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import checker  # noqa: E402
import cleaner  # noqa: E402


class FakeObject:
    def __init__(self, key, type_="Normal"):
        self.key = key
        self.type = type_


class FakeBucket:
    def __init__(self):
        self.deleted = []

    def delete_object(self, key):
        self.deleted.append(key)


class FailingBucket(FakeBucket):
    def delete_object(self, key):
        raise RuntimeError("oss down")


def fake_iterate(objects):
    def iterate(bucket, prefix):
        return iter(objects)
    return iterate


class DeleteObjectsTest(unittest.TestCase):
    def test_deletes_every_key(self):
        bucket = FakeBucket()
        deleted = cleaner.delete_objects(bucket, ["stacks/a", "stacks/b"])
        self.assertEqual(deleted, 2)
        self.assertEqual(bucket.deleted, ["stacks/a", "stacks/b"])

    def test_dry_run_deletes_nothing(self):
        bucket = FakeBucket()
        deleted = cleaner.delete_objects(bucket, ["stacks/a"], dry_run=True)
        self.assertEqual(deleted, 1)
        self.assertEqual(bucket.deleted, [])

    def test_failures_are_not_counted_as_deleted(self):
        deleted = cleaner.delete_objects(FailingBucket(), ["stacks/a", "stacks/b"])
        self.assertEqual(deleted, 0)


def go_key(version, arch="amd64", flavour="debian-13"):
    return "stacks/go/go-%s-linux-%s-%s.tar.gz" % (version, arch, flavour)


class ParseObjectKeyTest(unittest.TestCase):
    def test_parses_stack_version_arch_and_flavour(self):
        self.assertEqual(
            checker.parse_object_key(go_key("1.24.5")),
            ("go", "1.24.5", "amd64", "debian-13"),
        )

    def test_stack_names_with_hyphens_stay_intact(self):
        key = "stacks/apollo-adminservice/apollo-adminservice-2.3.0-linux-arm64-debian-12.tar.gz"
        self.assertEqual(
            checker.parse_object_key(key),
            ("apollo-adminservice", "2.3.0", "arm64", "debian-12"),
        )

    def test_flavours_with_hyphens_stay_intact(self):
        key = "stacks/go/go-1.24.5-linux-amd64-debian-13.tar.gz"
        self.assertEqual(checker.parse_object_key(key), ("go", "1.24.5", "amd64", "debian-13"))

    def test_directory_markers_and_foreign_layouts_are_rejected(self):
        for key in (
            "stacks/go/",                                     # directory marker
            "stacks/go",                                      # not a .tar.gz
            "stacks/other/go-1.24.5-linux-amd64-debian-13.tar.gz",  # name != dir
            "stacks/go/go-1.24.5-linux-s390x-debian-13.tar.gz",    # foreign arch
            "stacks/a/b/go-1.24.5-linux-amd64-debian-13.tar.gz",   # nested
        ):
            with self.subTest(key=key):
                self.assertIsNone(checker.parse_object_key(key))


class RetentionGroupsTest(unittest.TestCase):
    def test_groups_real_objects_by_stack_arch_and_flavour(self):
        objects = [
            ("stacks/go/go-1.24.5-linux-amd64-debian-13.tar.gz", "Normal"),
            ("stacks/go/go-1.24.5-linux-arm64-debian-13.tar.gz", "Normal"),
            ("stacks/go/go-1.24.5-linux-amd64-debian-12.tar.gz", "Normal"),
        ]
        groups, skipped = cleaner.retention_groups(objects)
        self.assertEqual(
            sorted(groups),
            [("go", "amd64", "debian-12"), ("go", "amd64", "debian-13"),
             ("go", "arm64", "debian-13")],
        )
        self.assertEqual(
            groups[("go", "amd64", "debian-13")],
            {"1.24.5": "stacks/go/go-1.24.5-linux-amd64-debian-13.tar.gz"},
        )
        self.assertEqual(skipped, {"symlinks": 0, "unparsed": 0})

    def test_symlinks_and_foreign_keys_are_skipped(self):
        objects = [
            ("stacks/go/go-1.24-linux-amd64-debian-13.tar.gz", "Symlink"),
            ("stacks/go/", "Normal"),
            ("stacks/go/go-1.24.5-linux-amd64-debian-13.tar.gz", "Normal"),
            ("stacks/other/go-1.24.5-linux-amd64-debian-13.tar.gz", "Normal"),
        ]
        groups, skipped = cleaner.retention_groups(objects)
        self.assertEqual(list(groups), [("go", "amd64", "debian-13")])
        self.assertEqual(skipped, {"symlinks": 1, "unparsed": 2})

    def test_skip_stacks_excludes_their_groups(self):
        objects = [
            (go_key("1.24.5"), "Normal"),
            ("stacks/nginx/nginx-1.31.8-linux-amd64-debian-13.tar.gz", "Normal"),
        ]
        groups, _ = cleaner.retention_groups(objects, skip_stacks={"go"})
        self.assertEqual(list(groups), [("nginx", "amd64", "debian-13")])


class RetentionPruneTest(unittest.TestCase):
    def test_deletes_only_versions_beyond_the_newest_n(self):
        versions = ("1.24.5", "1.24.4", "1.24.3", "1.23.0", "1.22.0")
        groups, _ = cleaner.retention_groups([(go_key(v), "Normal") for v in versions])
        victims, lines = cleaner.retention_prune(groups, 3)
        self.assertEqual(
            victims, [go_key("1.22.0"), go_key("1.23.0")],
        )
        self.assertEqual(len(lines), 1)
        self.assertIn("go linux-amd64-debian-13", lines[0])
        self.assertIn("keeping 3 of 5", lines[0])
        self.assertIn("deleting 1.22.0, 1.23.0", lines[0])

    def test_ranks_semantically_not_lexicographically(self):
        # lexicographic order would keep 1.9.0/1.8.0/1.7.0 and delete
        # 1.10.0 - the newest minor line
        versions = ("1.7.0", "1.8.0", "1.9.0", "1.10.0")
        groups, _ = cleaner.retention_groups([(go_key(v), "Normal") for v in versions])
        victims, _ = cleaner.retention_prune(groups, 3)
        self.assertEqual(victims, [go_key("1.7.0")])

    def test_groups_are_pruned_independently(self):
        objects = [(go_key(v), "Normal") for v in ("1.24.5", "1.24.4", "1.24.3", "1.23.0")]
        objects += [(go_key("1.24.5", arch="arm64"), "Normal"),
                    (go_key("1.23.0", arch="arm64"), "Normal")]
        groups, _ = cleaner.retention_groups(objects)
        victims, _ = cleaner.retention_prune(groups, 1)
        self.assertEqual(
            sorted(victims),
            sorted([go_key("1.23.0"), go_key("1.24.4"), go_key("1.24.3"),
                    go_key("1.23.0", arch="arm64")]),
        )

    def test_unparseable_versions_are_kept(self):
        # their age is unknown; checker.retention_keep always keeps them
        objects = [(go_key("weird"), "Normal"), (go_key("1.24.5"), "Normal")]
        groups, _ = cleaner.retention_groups(objects)
        victims, _ = cleaner.retention_prune(groups, 1)
        self.assertEqual(victims, [])

    def test_groups_within_the_count_produce_no_victims(self):
        versions = ("1.24.5", "1.24.4")
        groups, _ = cleaner.retention_groups([(go_key(v), "Normal") for v in versions])
        victims, lines = cleaner.retention_prune(groups, 3)
        self.assertEqual(victims, [])
        self.assertEqual(lines, [])


class RetentionCliTest(unittest.TestCase):
    def setUp(self):
        self.objects = [
            FakeObject(go_key("1.24.5")),
            FakeObject(go_key("1.24.4")),
            FakeObject(go_key("1.24.3")),
            FakeObject(go_key("1.23.0")),
            FakeObject(go_key("1.24"), "Symlink"),  # version pointer
        ]
        self.bucket = FakeBucket()

    def run_cli(self, argv, inputs=None):
        stdout = io.StringIO()
        with mock.patch("cleaner._oss_bucket", return_value=self.bucket), \
                mock.patch("cleaner.oss2.ObjectIterator", fake_iterate(self.objects)), \
                mock.patch("builtins.input",
                           side_effect=inputs if inputs is not None else ["y"]), \
                redirect_stdout(stdout):
            rc = cleaner.main(argv)
        return rc, stdout.getvalue()

    def test_confirm_prunes_beyond_top_n(self):
        rc, out = self.run_cli(["oss-stacks", "-n", "3", "--confirm"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.bucket.deleted, [go_key("1.23.0")])
        self.assertIn("keeping 3 of 4", out)
        self.assertIn("deleting 1.23.0", out)

    def test_symlinks_are_never_deleted(self):
        self.run_cli(["oss-stacks", "-n", "3", "--confirm"])
        self.assertNotIn(go_key("1.24"), self.bucket.deleted)

    def test_dry_run_lists_without_deleting(self):
        rc, out = self.run_cli(["oss-stacks", "-n", "3", "--dry-run"], inputs=[])
        self.assertEqual(rc, 0)
        self.assertEqual(self.bucket.deleted, [])
        self.assertIn("[DRY RUN] Would delete: %s" % go_key("1.23.0"), out)

    def test_declined_prompt_keeps_objects(self):
        rc, out = self.run_cli(["oss-stacks", "-n", "3"], inputs=["n"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.bucket.deleted, [])
        self.assertIn("Aborted", out)

    def test_nothing_to_prune_is_a_noop_without_prompting(self):
        objects = [FakeObject(go_key("1.24.5")), FakeObject(go_key("1.24.4"))]
        with mock.patch("cleaner._oss_bucket", return_value=self.bucket), \
                mock.patch("cleaner.oss2.ObjectIterator", fake_iterate(objects)), \
                mock.patch("builtins.input", side_effect=AssertionError("must not prompt")):
            rc = cleaner.main(["oss-stacks", "-n", "3"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.bucket.deleted, [])

    def test_deletion_failure_returns_non_zero(self):
        with mock.patch("cleaner._oss_bucket", return_value=FailingBucket()), \
                mock.patch("cleaner.oss2.ObjectIterator", fake_iterate(self.objects)):
            rc = cleaner.main(["oss-stacks", "-n", "3", "--confirm"])
        self.assertEqual(rc, 1)

    def test_suffix_option_is_rejected(self):
        # the suffix purge was retired: -n retention is the only cleanup
        # mode, and --skip-stack is its exclusion filter, not a second mode
        with mock.patch("cleaner._oss_bucket", return_value=self.bucket), \
                mock.patch("cleaner.oss2.ObjectIterator", fake_iterate(self.objects)):
            with self.assertRaises(SystemExit) as ctx:
                cleaner.main([
                    "oss-stacks", "-s", "linux-amd64-debian-13.tar.gz", "--dry-run",
                ])
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_keep_count_is_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            cleaner.main(["oss-stacks"])
        self.assertEqual(ctx.exception.code, 2)

    def test_zero_keep_count_is_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            cleaner.main(["oss-stacks", "-n", "0"])
        self.assertEqual(ctx.exception.code, 2)


def nginx_key(version, arch="amd64", flavour="debian-13"):
    return "stacks/nginx/nginx-%s-linux-%s-%s.tar.gz" % (version, arch, flavour)


class SkipStacksCliTest(unittest.TestCase):
    """--skip-stack protects named stacks from -n, including their
    symlinks. Stacks are named by their OSS directory, repeatable or
    comma-separated."""

    def setUp(self):
        self.objects = [
            FakeObject(go_key("1.24.5")),
            FakeObject(go_key("1.24.4")),
            FakeObject(go_key("1.23.0")),
            FakeObject(go_key("1.24"), "Symlink"),
            FakeObject(nginx_key("1.31.9")),
            FakeObject(nginx_key("1.31.8")),
            FakeObject(nginx_key("1.30.0")),
        ]
        self.bucket = FakeBucket()

    def run_cli(self, argv):
        stdout = io.StringIO()
        with mock.patch("cleaner._oss_bucket", return_value=self.bucket), \
                mock.patch("cleaner.oss2.ObjectIterator", fake_iterate(self.objects)), \
                mock.patch("builtins.input", side_effect=["y"]), \
                redirect_stdout(stdout):
            rc = cleaner.main(argv)
        return rc, stdout.getvalue()

    def test_n_skips_the_named_stacks(self):
        rc, out = self.run_cli(
            ["oss-stacks", "-n", "2", "--skip-stack", "go", "--confirm"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.bucket.deleted, [nginx_key("1.30.0")])
        self.assertIn("excluding stack(s): go", out)

    def test_comma_separated_skip_list(self):
        rc, out = self.run_cli(
            ["oss-stacks", "-n", "2", "--skip-stack", "go,nginx", "--confirm"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.bucket.deleted, [])
        self.assertIn("excluding stack(s): go,nginx", out)

    def test_repeatable_skip_flags(self):
        rc, _ = self.run_cli([
            "oss-stacks", "-n", "2",
            "--skip-stack", "go", "--skip-stack", "nginx", "--confirm",
        ])
        self.assertEqual(rc, 0)
        self.assertEqual(self.bucket.deleted, [])


if __name__ == "__main__":
    unittest.main()
