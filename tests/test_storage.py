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
from types import SimpleNamespace

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


class FakeBucket:
    def __init__(self):
        self.objects = {}

    def put_object(self, key, data):
        self.objects[key] = data
        return SimpleNamespace(status=200)


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


if __name__ == "__main__":
    unittest.main()
