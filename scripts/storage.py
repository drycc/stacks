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
    "go": ["1.16", "1.17", "1.18", "1.19", "1.20"],
    "java": ["8", "11", "17", "18", "19", "20", "21", "22"],
    "node": ["12", "14", "16", "17", "18", "19", "20"],
    "php": ["7.3", "7.4", "8.0", "8.1", "8.2"],
    "python": ["2.7", "3.7", "3.8", "3.9", "3.10", "3.11", "3.12"],
    "ruby": ["2.6", "3.7", "3.0", "3.1", "3.2", "3.3"],
    "rust": ["1"],
}


def upload(filename, filepath):
    with open(filepath, "rb") as f:
        result = bucket.put_object(filename, f.read())
        print("upload %s %s" % (filename, result.status))


def upload_list(stack_name, dist_dir):
    for root, _, files in os.walk(os.path.join(dist_dir, stack_name)):
        for _filename in  files:
            if _filename.startswith(stack_name) and _filename.endswith(".tar.gz"):
                filename = os.path.join("stacks", stack_name, _filename)
                filepath = os.path.join(root, _filename)
                upload(filename, filepath)
                if stack_name in symlink_table:
                    for symlink_version in symlink_table[stack_name]:
                        prefix = f"stacks/{stack_name}/{stack_name}-{symlink_version}"
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