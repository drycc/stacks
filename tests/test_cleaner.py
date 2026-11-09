"""Tests for scripts/cleaner.py.

The cleaner has one cleanup mode: per (stack, series, arch, flavour)
group, keep the newest N versions and delete the older ones. The nightly
planner rolls forward within the same series, so pruned versions are not
planned again. A local retention list protects whole stacks (python) or
exact versions (valkey==3.15) from deletion; it replaces the retired
--skip-stack flag.

Version-pointer symlinks (go-1.24 -> go-1.24.5 style) are never deleted;
the tests pin that -n leaves them alone and that retention list rules are
honoured across arches and flavours.

Run: .venv/bin/python -m unittest discover -s tests -p 'test_cleaner.py' -v
"""

import io
import os
import sys
import tempfile
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


class FakeSymlinkResult:
    def __init__(self, target_key):
        self.target_key = target_key


class FakeBucket:
    def __init__(self):
        self.deleted = []
        self.symlinks = {}
        self.symlink_calls = []

    def delete_object(self, key):
        self.deleted.append(key)

    def get_symlink(self, key):
        self.symlink_calls.append(key)
        return FakeSymlinkResult(self.symlinks.get(key, key))


class FailingBucket(FakeBucket):
    def delete_object(self, key):
        raise RuntimeError("oss down")


class FailingSymlinkBucket(FakeBucket):
    def get_symlink(self, key):
        raise RuntimeError("symlink lookup failed")


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


class RetentionListParseTest(unittest.TestCase):
    def test_parses_bare_stacks_and_exact_version_pins(self):
        stacks, versions = cleaner.parse_retention_list([
            "# currently used stacks\n",
            "\n",
            " python \n",
            "valkey == 3.15 \n",
            "redis==7.0.12\n",
            "python\n",                 # duplicate
            "valkey==3.15\n",           # duplicate
        ])
        self.assertEqual(stacks, {"python"})
        self.assertEqual(versions, {("valkey", "3.15"), ("redis", "7.0.12")})

    def test_single_equals_is_rejected_with_a_line_number(self):
        with self.assertRaisesRegex(ValueError, r"line 2.*=="):
            cleaner.parse_retention_list(["python\n", "valkey=3.15\n"])

    def test_malformed_entries_are_rejected(self):
        for entry in (
            "==3.15",             # missing stack
            "valkey==",           # missing version
            "valkey==3.15==1",    # more than one separator
            "val key",            # invalid stack name
            "valkey==3.15 rc1",   # whitespace inside version
        ):
            with self.subTest(entry=entry):
                with self.assertRaises(ValueError):
                    cleaner.parse_retention_list([entry + "\n"])

    def test_default_retention_list_file_is_valid(self):
        stacks, _ = cleaner.load_retention_list(cleaner.DEFAULT_RETENTION_LIST)
        self.assertTrue({"go", "java", "node", "php", "python", "ruby", "rust"} <= stacks)


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
            [("go", "1.24", "amd64", "debian-12"), ("go", "1.24", "amd64", "debian-13"),
             ("go", "1.24", "arm64", "debian-13")],
        )
        self.assertEqual(
            groups[("go", "1.24", "amd64", "debian-13")],
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
        self.assertEqual(list(groups), [("go", "1.24", "amd64", "debian-13")])
        self.assertEqual(skipped, {"symlinks": 1, "unparsed": 2})

    def test_bare_stack_entries_are_excluded_from_their_groups(self):
        objects = [
            (go_key("1.24.5"), "Normal"),
            ("stacks/nginx/nginx-1.31.8-linux-amd64-debian-13.tar.gz", "Normal"),
        ]
        groups, _ = cleaner.retention_groups(objects, protected_stacks={"go"})
        self.assertEqual(list(groups), [("nginx", "1.31", "amd64", "debian-13")])


    def test_exact_pins_veto_victims_and_are_reported_separately(self):
        versions = ("1.24.5", "1.24.4", "1.24.3", "1.24.2", "1.24.1")
        objects = [(go_key(version), "Normal") for version in versions]
        objects += [(go_key(version, arch="arm64"), "Normal") for version in versions]
        groups, _ = cleaner.retention_groups(objects)
        victims, lines, protected = cleaner.retention_prune(
            groups, 2, {("go", "1.24.3")})
        self.assertEqual(
            victims,
            [go_key("1.24.1"), go_key("1.24.2"),
             go_key("1.24.1", arch="arm64"), go_key("1.24.2", arch="arm64")],
        )
        self.assertEqual(
            protected,
            [go_key("1.24.3"), go_key("1.24.3", arch="arm64")],
        )
        summary = "\n".join(lines)
        self.assertNotIn("deleting 1.24.3", summary)
        self.assertEqual(summary.count("retention list protecting 1.24.3"), 2)

    def test_a_pin_does_not_match_a_longer_version(self):
        versions = ("3.15.1", "3.15.0")
        groups, _ = cleaner.retention_groups([(go_key(v), "Normal") for v in versions])
        victims, _, protected = cleaner.retention_prune(groups, 1, {("go", "3.15")})
        self.assertEqual(victims, [go_key("3.15.0")])
        self.assertEqual(protected, [])


class RetentionPruneTest(unittest.TestCase):
    def test_deletes_only_versions_beyond_the_newest_n(self):
        versions = ("1.24.5", "1.24.4", "1.24.3", "1.24.2", "1.24.1")
        groups, _ = cleaner.retention_groups([(go_key(v), "Normal") for v in versions])
        victims, lines, protected = cleaner.retention_prune(groups, 3)
        self.assertEqual(
            victims, [go_key("1.24.1"), go_key("1.24.2")],
        )
        self.assertEqual(len(lines), 1)
        self.assertIn("go/1.24 linux-amd64-debian-13", lines[0])
        self.assertIn("keeping 3 of 5", lines[0])
        self.assertIn("deleting 1.24.1, 1.24.2", lines[0])

    def test_each_series_has_an_independent_retention_window(self):
        versions = ("7.18.2", "7.18.1", "8.0.1", "8.0.0")
        groups, _ = cleaner.retention_groups([(go_key(v), "Normal") for v in versions])
        victims, _, _ = cleaner.retention_prune(groups, 1)
        self.assertEqual(victims, [go_key("7.18.1"), go_key("8.0.0")])

    def test_ranks_semantically_not_lexicographically(self):
        # lexicographic order would keep 1.31.9/1.31.8/1.31.7 and delete
        # 1.31.10 - the newest patch in the same series
        versions = ("1.31.7", "1.31.8", "1.31.9", "1.31.10")
        groups, _ = cleaner.retention_groups([(go_key(v), "Normal") for v in versions])
        victims, _, _ = cleaner.retention_prune(groups, 3)
        self.assertEqual(victims, [go_key("1.31.7")])

    def test_groups_are_pruned_independently(self):
        objects = [(go_key(v), "Normal") for v in ("1.24.5", "1.24.4", "1.24.3")]
        objects += [(go_key("1.24.5", arch="arm64"), "Normal"),
                    (go_key("1.24.4", arch="arm64"), "Normal")]
        groups, _ = cleaner.retention_groups(objects)
        victims, _, _ = cleaner.retention_prune(groups, 1)
        self.assertEqual(
            sorted(victims),
            sorted([go_key("1.24.4"), go_key("1.24.3"),
                    go_key("1.24.4", arch="arm64")]),
        )

    def test_unparseable_versions_are_kept(self):
        # their age is unknown; checker.retention_keep always keeps them
        objects = [(go_key("weird"), "Normal"), (go_key("1.24.5"), "Normal")]
        groups, _ = cleaner.retention_groups(objects)
        victims, _, _ = cleaner.retention_prune(groups, 1)
        self.assertEqual(victims, [])

    def test_groups_within_the_count_produce_no_victims(self):
        versions = ("1.24.5", "1.24.4")
        groups, _ = cleaner.retention_groups([(go_key(v), "Normal") for v in versions])
        victims, lines, protected = cleaner.retention_prune(groups, 3)
        self.assertEqual(victims, [])
        self.assertEqual(lines, [])


class RetentionCliTest(unittest.TestCase):
    def setUp(self):
        self.objects = [
            FakeObject(go_key("1.24.5")),
            FakeObject(go_key("1.24.4")),
            FakeObject(go_key("1.24.3")),
            FakeObject(go_key("1.24.2")),
            FakeObject(go_key("1.24"), "Symlink"),  # version pointer
        ]
        self.bucket = FakeBucket()
        # Keep these tests independent of the repository's real retention list.
        self._tmp = tempfile.TemporaryDirectory()
        retention_list = os.path.join(self._tmp.name, "retention_list.txt")
        with open(retention_list, "w") as f:
            f.write("")
        self._default = mock.patch("cleaner.DEFAULT_RETENTION_LIST", retention_list, create=True)
        self._default.start()

    def tearDown(self):
        self._default.stop()
        self._tmp.cleanup()

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
        self.assertEqual(self.bucket.deleted, [go_key("1.24.2")])
        self.assertIn("keeping 3 of 4", out)
        self.assertIn("per series/arch/flavour", out)
        self.assertIn("deleting 1.24.2", out)

    def test_symlinks_are_never_deleted(self):
        self.run_cli(["oss-stacks", "-n", "3", "--confirm"])
        self.assertNotIn(go_key("1.24"), self.bucket.deleted)

    def test_dry_run_lists_without_deleting(self):
        rc, out = self.run_cli(["oss-stacks", "-n", "3", "--dry-run"], inputs=[])
        self.assertEqual(rc, 0)
        self.assertEqual(self.bucket.deleted, [])
        self.assertIn("[DRY RUN] Would delete: %s" % go_key("1.24.2"), out)

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
        # mode, and the retention list is its protection filter, not a second mode
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


class SymlinkAndArchCliTest(unittest.TestCase):
    def setUp(self):
        self.bucket = FakeBucket()
        self._tmp = tempfile.TemporaryDirectory()
        self.retention_list = os.path.join(self._tmp.name, "retention-list.txt")
        with open(self.retention_list, "w") as f:
            f.write("")

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, objects, argv):
        stdout = io.StringIO()
        with mock.patch("cleaner._oss_bucket", return_value=self.bucket), \
                mock.patch("cleaner.oss2.ObjectIterator", fake_iterate(objects)), \
                mock.patch("builtins.input", side_effect=["y"]), \
                redirect_stdout(stdout):
            try:
                rc = cleaner.main(argv + ["--retention-list", self.retention_list])
            except SystemExit as exc:
                rc = exc.code
        return rc, stdout.getvalue()

    def test_only_the_symlink_and_its_target_are_protected(self):
        objects = [
            FakeObject(go_key("1.24.13")),
            FakeObject(go_key("1.24.12")),
            FakeObject(go_key("1.24.11")),
            FakeObject(go_key("1.24"), "Symlink"),
        ]
        self.bucket.symlinks[go_key("1.24")] = go_key("1.24.12")
        rc, out = self.run_cli(objects, ["oss-stacks", "-n", "1", "--confirm"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.bucket.deleted, [go_key("1.24.11")])
        self.assertNotIn(go_key("1.24.12"), self.bucket.deleted)
        self.assertIn("symlink protecting 1.24.12", out)

    def test_symlink_target_failure_aborts_before_deletion(self):
        self.bucket = FailingSymlinkBucket()
        objects = [
            FakeObject(go_key("1.24.13")),
            FakeObject(go_key("1.24.12")),
            FakeObject(go_key("1.24"), "Symlink"),
        ]
        rc, _ = self.run_cli(objects, ["oss-stacks", "-n", "1", "--confirm"])
        self.assertEqual(rc, 1)
        self.assertEqual(self.bucket.deleted, [])

    def test_arch_filter_limits_deletion_and_target_lookups(self):
        objects = []
        for arch in ("amd64", "arm64"):
            objects.extend([
                FakeObject(go_key("1.24.13", arch=arch)),
                FakeObject(go_key("1.24.12", arch=arch)),
                FakeObject(go_key("1.24.11", arch=arch)),
                FakeObject(go_key("1.24", arch=arch), "Symlink"),
            ])
            self.bucket.symlinks[go_key("1.24", arch=arch)] = go_key("1.24.12", arch=arch)
        rc, out = self.run_cli(objects, ["oss-stacks", "-n", "1", "--arch", "arm64", "--confirm"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.bucket.deleted, [go_key("1.24.11", arch="arm64")])
        self.assertEqual(self.bucket.symlink_calls, [go_key("1.24", arch="arm64")])
        self.assertIn("skipping 1 symlink(s)", out)


    def test_unparsable_symlink_aborts_instead_of_deleting_its_target(self):
        objects = [
            FakeObject("stacks/nginx/latest.tar.gz", "Symlink"),
            FakeObject(nginx_key("1.31.9")),
            FakeObject(nginx_key("1.31.8")),
        ]
        self.bucket.symlinks["stacks/nginx/latest.tar.gz"] = nginx_key("1.31.8")
        rc, _ = self.run_cli(objects, ["oss-stacks", "-n", "1", "--confirm"])
        self.assertEqual(rc, 1)
        self.assertEqual(self.bucket.deleted, [])

    def test_overlapping_pin_and_symlink_protection_is_counted_once(self):
        objects = [
            FakeObject(go_key("1.24.13")),
            FakeObject(go_key("1.24.12")),
            FakeObject(go_key("1.24.11")),
            FakeObject(go_key("1.24"), "Symlink"),
        ]
        self.bucket.symlinks[go_key("1.24")] = go_key("1.24.12")
        with open(self.retention_list, "w") as f:
            f.write("go==1.24.12\n")
        rc, out = self.run_cli(objects, ["oss-stacks", "-n", "1", "--confirm"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.bucket.deleted, [go_key("1.24.11")])
        self.assertIn("1 protected object(s)", out)
        self.assertIn("keeping 2 of 3", out)

    def test_symlink_only_noop_message_does_not_blame_the_retention_list(self):
        objects = [
            FakeObject(go_key("1.24.13")),
            FakeObject(go_key("1.24.12")),
            FakeObject(go_key("1.24"), "Symlink"),
        ]
        self.bucket.symlinks[go_key("1.24")] = go_key("1.24.12")
        rc, out = self.run_cli(objects, ["oss-stacks", "-n", "1", "--confirm"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.bucket.deleted, [])
        self.assertIn("all versions beyond retention are protected.", out)
        self.assertNotIn("protected by the retention list", out)


class RetentionListCliTest(unittest.TestCase):
    def setUp(self):
        self.objects = [
            FakeObject(go_key("1.24.5")),
            FakeObject(go_key("1.24.4")),
            FakeObject(go_key("1.24.3")),
            FakeObject(go_key("1.24.2")),
            FakeObject(go_key("1.24"), "Symlink"),
            FakeObject(nginx_key("1.31.9")),
            FakeObject(nginx_key("1.31.8")),
            FakeObject(nginx_key("1.31.7")),
        ]
        self.bucket = FakeBucket()
        self._tmp = tempfile.TemporaryDirectory()
        self.retention_list_path = os.path.join(self._tmp.name, "retention_list.txt")

    def tearDown(self):
        self._tmp.cleanup()

    def write_retention_list(self, text):
        with open(self.retention_list_path, "w") as f:
            f.write(text)

    def run_cli(self, argv):
        stdout = io.StringIO()
        with mock.patch("cleaner._oss_bucket", return_value=self.bucket), \
                mock.patch("cleaner.oss2.ObjectIterator", fake_iterate(self.objects)), \
                mock.patch("builtins.input", side_effect=["y"]), \
                redirect_stdout(stdout):
            try:
                rc = cleaner.main(argv + ["--retention-list", self.retention_list_path])
            except SystemExit as exc:
                rc = exc.code
        return rc, stdout.getvalue()

    def test_bare_stack_protects_every_version(self):
        self.write_retention_list("go\n")
        rc, out = self.run_cli(["oss-stacks", "-n", "2", "--confirm"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.bucket.deleted, [nginx_key("1.31.7")])
        self.assertIn("1 stack rule(s)", out)

    def test_exact_pin_is_an_extra_veto_outside_retention(self):
        self.write_retention_list("go==1.24.3\n")
        rc, out = self.run_cli(["oss-stacks", "-n", "2", "--confirm"])
        self.assertEqual(rc, 0)
        self.assertEqual(
            self.bucket.deleted,
            [go_key("1.24.2"), nginx_key("1.31.7")],
        )
        self.assertIn("1 protected object(s)", out)
        self.assertIn("2 object(s) scheduled for deletion", out)
        self.assertIn("keeping 3 of 4", out)
        self.assertIn("retention list protecting 1.24.3", out)
        self.assertNotIn("deleting 1.24.2, 1.24.3", out)

    def test_all_outdated_versions_protected_still_reports_the_protection(self):
        self.objects = [
            FakeObject(go_key("1.24.5")),
            FakeObject(go_key("1.24.4")),
            FakeObject(go_key("1.24.3")),
        ]
        self.write_retention_list("go==1.24.3\n")
        rc, out = self.run_cli(["oss-stacks", "-n", "2", "--confirm"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.bucket.deleted, [])
        self.assertIn("retention list protecting 1.24.3", out)
        self.assertIn("all versions beyond retention are protected.", out)
        self.assertNotIn("every group is within the retention count", out)

    def test_a_pin_does_not_change_the_underlying_retention_ranking(self):
        # 1.24.4 is already inside newest-2, so the pin protects no
        # additional object and both older versions are still pruned.
        self.write_retention_list("go==1.24.4\n")
        rc, out = self.run_cli(["oss-stacks", "-n", "2", "--confirm"])
        self.assertEqual(rc, 0)
        self.assertEqual(
            self.bucket.deleted,
            [go_key("1.24.2"), go_key("1.24.3"), nginx_key("1.31.7")],
        )
        self.assertIn("0 protected object(s)", out)

    def test_missing_retention_list_aborts_before_oss(self):
        missing = os.path.join(self._tmp.name, "missing.txt")
        with mock.patch("cleaner.DEFAULT_RETENTION_LIST", missing, create=True), \
                mock.patch("cleaner._oss_bucket", return_value=self.bucket) as bucket, \
                mock.patch("cleaner.oss2.ObjectIterator", fake_iterate(self.objects)):
            with self.assertRaises(SystemExit) as ctx:
                cleaner.main(["oss-stacks", "-n", "2", "--dry-run"])
        self.assertEqual(ctx.exception.code, 2)
        bucket.assert_not_called()

    def test_malformed_retention_list_aborts_before_oss(self):
        self.write_retention_list("go=1.23.0\n")
        with mock.patch("cleaner.DEFAULT_RETENTION_LIST", self.retention_list_path, create=True), \
                mock.patch("cleaner._oss_bucket", return_value=self.bucket) as bucket, \
                mock.patch("cleaner.oss2.ObjectIterator", fake_iterate(self.objects)):
            with self.assertRaises(SystemExit) as ctx:
                cleaner.main(["oss-stacks", "-n", "2", "--dry-run"])
        self.assertEqual(ctx.exception.code, 2)
        bucket.assert_not_called()

    def test_skip_stack_option_is_rejected(self):
        self.write_retention_list("")
        with mock.patch("cleaner.DEFAULT_RETENTION_LIST", self.retention_list_path, create=True), \
                mock.patch("cleaner._oss_bucket", return_value=self.bucket), \
                mock.patch("cleaner.oss2.ObjectIterator", fake_iterate(self.objects)):
            with self.assertRaises(SystemExit) as ctx:
                cleaner.main([
                    "oss-stacks", "-n", "2", "--skip-stack", "go", "--dry-run",
                ])
        self.assertEqual(ctx.exception.code, 2)

    def test_legacy_whitelist_option_is_rejected(self):
        self.write_retention_list("")
        with mock.patch("cleaner.DEFAULT_RETENTION_LIST", self.retention_list_path, create=True), \
                mock.patch("cleaner._oss_bucket", return_value=self.bucket), \
                mock.patch("cleaner.oss2.ObjectIterator", fake_iterate(self.objects)):
            with self.assertRaises(SystemExit) as ctx:
                cleaner.main([
                    "oss-stacks", "-n", "2", "--whitelist", self.retention_list_path,
                    "--dry-run",
                ])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
