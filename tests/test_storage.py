"""Empty-package guard tests for scripts/storage.py.

validate_package must reject tar.gz archives that hold nothing but
scaffolding (empty directories, meta/ files and data/profile.d/), and
upload() must call it before touching OSS, so a failed build can no longer
be uploaded as an empty package.

Run: .venv/bin/python -m unittest discover -s tests -p 'test_storage.py' -v
"""

import io
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest import mock

# oss2.Auth requires credentials at import time; tests never talk to OSS
# (the bucket is replaced with a fake), so dummy values are enough.
os.environ.setdefault("OSS_ACCESS_KEY_ID", "test-access-key-id")
os.environ.setdefault("OSS_ACCESS_KEY_SECRET", "test-access-key-secret")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import storage  # noqa: E402


def write_package(path, entries):
    """Create a tar.gz fixture.

    entries is a list of (arcname, kind, data) tuples where kind is one of
    "dir", "file", "sym" or "lnk"; for "file" data is the payload bytes, for
    "sym"/"lnk" it is the link target.
    """
    with tarfile.open(path, "w:gz") as tar:
        for arcname, kind, data in entries:
            info = tarfile.TarInfo(arcname)
            if kind == "dir":
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tar.addfile(info)
            elif kind == "file":
                info.size = len(data)
                info.mode = 0o755
                tar.addfile(info, io.BytesIO(data))
            elif kind == "sym":
                info.type = tarfile.SYMTYPE
                info.linkname = data
                info.mode = 0o777
                tar.addfile(info)
            elif kind == "lnk":
                info.type = tarfile.LNKTYPE
                info.linkname = data
                info.mode = 0o755
                tar.addfile(info)
            else:
                raise ValueError("unknown entry kind: %s" % kind)


def scaffold_entries():
    """What generate-stack-template leaves behind in a failed build."""
    return [
        ("data", "dir", b""),
        ("data/bin", "dir", b""),
        ("data/profile.d", "dir", b""),
        ("data/profile.d/teststack.sh", "file", b"export PATH\n"),
        ("meta", "dir", b""),
        ("meta/dependencies", "file", b""),
        ("meta/preinstall", "file", b""),
        ("meta/postinstall", "file", b""),
    ]


class FakeObject:
    def __init__(self, key, type="Normal"):
        self.key = key
        self.type = type


class FakeBucket:
    def __init__(self, objects=(), error=None):
        self.objects = {}
        self.listing = list(objects)
        self.error = error
        self.prefixes = []

    def put_object(self, key, data):
        self.objects[key] = data
        return SimpleNamespace(status=200)

    def list_objects(self, prefix="", **kwargs):
        self.prefixes.append(prefix)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            object_list=[obj for obj in self.listing if obj.key.startswith(prefix)]
        )


ARTIFACT_KEY = "stacks/nginx/nginx-1.31.8-linux-amd64-debian-13.tar.gz"
ARM_ARTIFACT_KEY = "stacks/nginx/nginx-1.31.8-linux-arm64-debian-13.tar.gz"


class ArtifactExistsTest(unittest.TestCase):
    def test_exact_normal_object_exists_and_uses_exact_prefix(self):
        bucket = FakeBucket([FakeObject(ARTIFACT_KEY)])
        self.assertTrue(storage.artifact_exists(
            "nginx", "1.31.8", "amd64", "debian-13", bucket=bucket,
        ))
        self.assertEqual(bucket.prefixes, [ARTIFACT_KEY])

    def test_another_prefixed_object_does_not_count(self):
        bucket = FakeBucket([FakeObject(ARTIFACT_KEY + ".partial")])
        self.assertFalse(storage.artifact_exists(
            "nginx", "1.31.8", "amd64", "debian-13", bucket=bucket,
        ))

    def test_symlink_only_object_does_not_count(self):
        key = ARTIFACT_KEY
        self.assertFalse(storage.artifact_exists(
            "nginx", "1.31.8", "amd64", "debian-13",
            bucket=FakeBucket([FakeObject(key, type="Symlink")]),
        ))

    def test_missing_object_does_not_count(self):
        self.assertFalse(storage.artifact_exists(
            "nginx", "1.31.8", "amd64", "debian-13", bucket=FakeBucket(),
        ))

    def test_bucket_errors_propagate(self):
        bucket = FakeBucket(error=RuntimeError("oss 500"))
        with self.assertRaisesRegex(RuntimeError, "oss 500"):
            storage.artifact_exists(
                "nginx", "1.31.8", "amd64", "debian-13", bucket=bucket,
            )


class ArtifactExistsCliTest(unittest.TestCase):
    def setUp(self):
        self._orig_bucket = storage.bucket

    def tearDown(self):
        storage.bucket = self._orig_bucket

    def run_cli(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = storage.main(argv)
        return rc, stdout.getvalue(), stderr.getvalue()

    def test_exact_normal_object_returns_zero(self):
        storage.bucket = FakeBucket([FakeObject(ARTIFACT_KEY)])
        rc, _, _ = self.run_cli([
            "artifact-exists", "nginx", "1.31.8",
            "--arch", "amd64", "--flavour", "debian-13",
        ])
        self.assertEqual(rc, 0)

    def test_missing_or_symlink_only_object_returns_one(self):
        cases = (
            ("missing", ()),
            ("symlink", (FakeObject(ARTIFACT_KEY, type="Symlink"),)),
        )
        for name, objects in cases:
            with self.subTest(case=name):
                storage.bucket = FakeBucket(objects)
                rc, _, _ = self.run_cli([
                    "artifact-exists", "nginx", "1.31.8",
                    "--arch", "amd64", "--flavour", "debian-13",
                ])
                self.assertEqual(rc, 1)

    def test_bucket_error_returns_two(self):
        storage.bucket = FakeBucket(error=RuntimeError("oss 500"))
        rc, _, stderr = self.run_cli([
            "artifact-exists", "nginx", "1.31.8",
            "--arch", "amd64", "--flavour", "debian-13",
        ])
        self.assertEqual(rc, 2)
        self.assertIn("oss 500", stderr)

    def test_auto_arch_and_flavour_detection(self):
        storage.bucket = FakeBucket([FakeObject(ARM_ARTIFACT_KEY)])
        for extra in ((), ("--arch", "auto", "--flavour", "auto")):
            with self.subTest(arguments=extra):
                with mock.patch("platform.machine", return_value="aarch64"), \
                        mock.patch("builtins.open", mock.mock_open(
                            read_data='ID=debian\nVERSION_ID="13"\n'
                        )):
                    rc, _, stderr = self.run_cli([
                        "artifact-exists", "nginx", "1.31.8", *extra,
                    ])
                self.assertEqual(rc, 0, stderr)
        self.assertEqual(storage.bucket.prefixes, [ARM_ARTIFACT_KEY, ARM_ARTIFACT_KEY])


class ValidatePackageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "teststack-1.0.0-linux-amd64-debian-13.tar.gz")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_scaffold_only_package_is_rejected(self):
        write_package(self.path, scaffold_entries())
        with self.assertRaises(ValueError):
            storage.validate_package(self.path)

    def test_empty_directories_only_is_rejected(self):
        write_package(
            self.path,
            [
                ("data", "dir", b""),
                ("data/bin", "dir", b""),
            ],
        )
        with self.assertRaises(ValueError):
            storage.validate_package(self.path)

    def test_regular_file_payload_is_accepted(self):
        write_package(
            self.path,
            scaffold_entries() + [("data/bin/teststack", "file", b"payload")],
        )
        storage.validate_package(self.path)

    def test_payload_outside_bin_is_accepted(self):
        write_package(
            self.path,
            scaffold_entries() + [("data/lib/libdemo.so", "file", b"payload")],
        )
        storage.validate_package(self.path)

    def test_symlink_payload_is_accepted(self):
        write_package(
            self.path,
            scaffold_entries() + [("data/bin/link", "sym", "teststack")],
        )
        storage.validate_package(self.path)

    def test_hardlink_payload_is_accepted(self):
        write_package(
            self.path,
            scaffold_entries()
            + [("data/bin/teststack", "file", b"payload"), ("data/bin/hardlink", "lnk", "data/bin/teststack")],
        )
        storage.validate_package(self.path)

    def test_missing_file_is_rejected(self):
        with self.assertRaises(ValueError):
            storage.validate_package(os.path.join(self.tmp, "missing.tar.gz"))

    def test_corrupt_archive_is_rejected(self):
        with open(self.path, "wb") as f:
            f.write(b"this is not a gzip file")
        with self.assertRaises(ValueError):
            storage.validate_package(self.path)

    def test_truncated_archive_is_rejected(self):
        write_package(self.path, scaffold_entries() + [("data/bin/teststack", "file", b"payload")])
        with open(self.path, "rb") as f:
            data = f.read()
        truncated = os.path.join(self.tmp, "truncated.tar.gz")
        with open(truncated, "wb") as f:
            f.write(data[: len(data) // 2])
        with self.assertRaises(ValueError):
            storage.validate_package(truncated)


class UploadGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "teststack-1.0.0-linux-amd64-debian-13.tar.gz")
        self._orig_bucket = storage.bucket
        storage.bucket = FakeBucket()

    def tearDown(self):
        storage.bucket = self._orig_bucket
        shutil.rmtree(self.tmp)

    def test_upload_rejects_scaffold_package_without_putting(self):
        write_package(self.path, scaffold_entries())
        with self.assertRaises(ValueError):
            storage.upload("stacks/teststack/teststack-1.0.0-linux-amd64-debian-13.tar.gz", self.path)
        self.assertEqual(storage.bucket.objects, {})

    def test_upload_puts_valid_package(self):
        write_package(
            self.path,
            scaffold_entries() + [("data/bin/teststack", "file", b"payload")],
        )
        key = "stacks/teststack/teststack-1.0.0-linux-amd64-debian-13.tar.gz"
        storage.upload(key, self.path)
        self.assertIn(key, storage.bucket.objects)

    def test_upload_list_raises_when_no_stack_archives_are_found(self):
        dist_dir = os.path.join(self.tmp, "dist")
        os.makedirs(os.path.join(dist_dir, "teststack"))
        with self.assertRaisesRegex(ValueError, "^no stack archives found$"):
            storage.upload_list("teststack", dist_dir)
        self.assertEqual(storage.bucket.objects, {})

    def test_upload_list_returns_uploaded_keys(self):
        dist_dir = os.path.join(self.tmp, "dist")
        archive_dir = os.path.join(dist_dir, "teststack")
        os.makedirs(archive_dir)
        archive_path = os.path.join(archive_dir, os.path.basename(self.path))
        write_package(
            archive_path,
            scaffold_entries() + [("data/bin/teststack", "file", b"payload")],
        )
        key = "stacks/teststack/teststack-1.0.0-linux-amd64-debian-13.tar.gz"
        self.assertEqual(storage.upload_list("teststack", dist_dir), [key])
        self.assertEqual(list(storage.bucket.objects), [key])


if __name__ == "__main__":
    unittest.main()
