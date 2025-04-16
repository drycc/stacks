import os
import re
import sys
import oss2


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
    symlink_list = []
    object_list = [
        obj.key for obj in bucket.list_objects(
            f"stacks/{stack_name}/{stack_name}-{version}.").object_list
    ]
    object_list.sort(reverse=True)
    for obj in object_list:
        name = f"stacks/{stack_name}/{stack_name}-{version}"
        symlink = re.sub("%s.([0-9]\.?){1,}" % name, name, obj)
        if symlink != obj and symlink not in symlink_list:
            bucket.put_symlink(obj, symlink)
            symlink_list.append(symlink)


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "upload":
        upload_list(sys.argv[2], sys.argv[3])
    elif action == "symlink":
        symlink(sys.argv[2], sys.argv[3])
    else:
        print("Unknown action: %s" % action)
