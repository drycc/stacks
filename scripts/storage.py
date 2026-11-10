import argparse
import os
import platform
import re
import sys
import tarfile
import oss2
from packaging.version import parse

import checker


bucket = oss2.Bucket(
    oss2.Auth(
        os.environ.get("OSS_ACCESS_KEY_ID"),
        os.environ.get("OSS_ACCESS_KEY_SECRET"),
    ),
    os.environ.get("OSS_ENDPOINT", "http://oss-accelerate.aliyuncs.com"),
    'drycc'
)

symlink_table = {
    "go": "[0-9]{1,}.[0-9]{1,}",
    "java": "[0-9]{1,}",
    "node": "[0-9]{1,}",
    "php": "[0-9]{1,}.[0-9]{1,}",
    "python": "[0-9]{1,}.[0-9]{1,}",
    "ruby": "[0-9]{1,}.[0-9]{1,}",
    "rust": "[0-9]{1,}",
}


def artifact_exists(stack, version, arch, flavour, bucket=None):
    """Return whether the exact normal (non-symlink) artifact exists."""
    if bucket is None:
        bucket = globals()["bucket"]
    expected = checker.object_key(stack, version, arch, flavour)
    result = bucket.list_objects(prefix=expected)
    return any(
        obj.key == expected and obj.type != "Symlink"
        for obj in result.object_list
    )


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


def _find_payload(tar):
    """Return the name of the first real payload member, or None.

    Works with both random-access and streaming tarfile objects. A real
    payload is a regular file, symlink or hard link under data/ outside
    data/profile.d/.
    """
    for member in tar:
        name = member.name
        if name.startswith("./"):
            name = name[2:]
        if not name.startswith("data/"):
            continue
        rest = name[len("data/"):].rstrip("/")
        if not rest or rest == "profile.d" or rest.startswith("profile.d/"):
            continue
        if member.isfile() or member.issym() or member.islnk():
            return member.name
    return None


def validate_package(filepath):
    """Raise ValueError unless the tar.gz archive holds a real payload.

    A real payload is at least one regular file, symlink or hard link under
    data/ outside data/profile.d/. Directory entries and meta/ scaffolding do
    not count, so a failed build can no longer be uploaded as an empty
    package.
    """
    try:
        with tarfile.open(filepath, "r:gz") as tar:
            payload = _find_payload(tar)
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise ValueError("invalid stack package %s: %s" % (filepath, exc)) from exc
    if payload is None:
        raise ValueError(
            "stack package %s contains no payload files under data/ (profile.d excluded)" % filepath
        )


def upload(filename, filepath):
    validate_package(filepath)
    with open(filepath, "rb") as f:
        result = bucket.put_object(filename, f.read())
        print("upload %s %s" % (filename, result.status))


def upload_list(stack_name, dist_dir):
    uploaded = []
    for root, _, files in os.walk(os.path.join(dist_dir, stack_name)):
        for _filename in files:
            if _filename.startswith(stack_name) and _filename.endswith(".tar.gz"):
                filename = os.path.join("stacks", stack_name, _filename)
                filepath = os.path.join(root, _filename)
                upload(filename, filepath)
                uploaded.append(filename)
                if stack_name in symlink_table:
                    version_regex = symlink_table[stack_name]
                    prefix = f"stacks/{stack_name}/{stack_name}-"
                    version = filename.replace(prefix, "").split("-")[0]
                    symlink_version = re.search(version_regex, version).group()
                    prefix += symlink_version
                    if filename.startswith(prefix):
                        symlink(stack_name, symlink_version)
    if not uploaded:
        raise ValueError("no stack archives found")
    return uploaded


def symlink(stack_name, version):

    def get_system_version(obj_key):
        _, system, system_version = obj_key.strip(".tar.gz").rsplit("-", 2)
        return f"{system}-{system_version}"

    object_list = [
        obj.key for obj in bucket.list_objects(
            f"stacks/{stack_name}/{stack_name}-{version}.").object_list
    ]
    prefix = f"stacks/{stack_name}/{stack_name}-"
    # Build a map of system-version to object keys
    version_map = {}
    for obj in object_list:
        system = get_system_version(obj)
        if system not in version_map:
            version_map[system] = [obj]
        else:
            version_map[system].append(obj)
    for key, value in version_map.items():
        version_list = sorted(
            [obj.replace(prefix, "").split("-", 1)[0] for obj in value],
            key=parse,
            reverse=True,
        )
        version_map[key] = version_list

    for obj in object_list:
        version_list = version_map[get_system_version(obj)]
        if obj.startswith(f"{prefix}{version_list[0]}-"):
            symlink = re.sub(r"%s.([0-9]\.?){1,}" % f"{prefix}{version}", f"{prefix}{version}", obj)
            bucket.put_symlink(obj, symlink)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="storage.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    upload_parser = subparsers.add_parser("upload")
    upload_parser.add_argument("stack")
    upload_parser.add_argument("dist_dir")
    symlink_parser = subparsers.add_parser("symlink")
    symlink_parser.add_argument("stack")
    symlink_parser.add_argument("version")
    exists_parser = subparsers.add_parser("artifact-exists")
    exists_parser.add_argument("stack")
    exists_parser.add_argument("version")
    exists_parser.add_argument("--arch", default="auto")
    exists_parser.add_argument("--flavour", default="auto")
    args = parser.parse_args(argv)

    if args.command == "upload":
        upload_list(args.stack, args.dist_dir)
        return 0
    if args.command == "symlink":
        symlink(args.stack, args.version)
        return 0
    if args.command == "artifact-exists":
        try:
            arch = detect_arch() if args.arch == "auto" else args.arch
            flavour = detect_flavour() if args.flavour == "auto" else args.flavour
            exists = artifact_exists(args.stack, args.version, arch, flavour)
        except Exception as exc:  # noqa: BLE001 - verification errors must not count as missing
            print("storage: artifact-exists failed: %s" % exc, file=sys.stderr)
            return 2
        return 0 if exists else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
