import os
import re
import sys
import oss2
from packaging.version import parse


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


def upload(filename, filepath):
    with open(filepath, "rb") as f:
        result = bucket.put_object(filename, f.read())
        print("upload %s %s" % (filename, result.status))


def upload_list(stack_name, dist_dir):
    for root, _, files in os.walk(os.path.join(dist_dir, stack_name)):
        for _filename in files:
            if _filename.startswith(stack_name) and _filename.endswith(".tar.gz"):
                filename = os.path.join("stacks", stack_name, _filename)
                filepath = os.path.join(root, _filename)
                upload(filename, filepath)
                if stack_name in symlink_table:
                    version_regex = symlink_table[stack_name]
                    prefix = f"stacks/{stack_name}/{stack_name}-"
                    version = filename.replace(prefix, "").split("-")[0]
                    symlink_version = re.search(version_regex, version).group()
                    prefix += symlink_version
                    if filename.startswith(prefix):
                        symlink(stack_name, symlink_version)


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


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "upload":
        upload_list(sys.argv[2], sys.argv[3])
    elif action == "symlink":
        symlink(sys.argv[2], sys.argv[3])
    else:
        print("Unknown action: %s" % action)
