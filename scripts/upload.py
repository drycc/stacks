import os
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


def upload(filename, filepath):
    with open(filepath, "rb") as f:
        result = bucket.put_object(filename, f.read())
        print("upload %s %s" % (filename, result.status))


def upload_list(stack_name, dist_dir):
    for root, _, files in os.walk(dist_dir):
        for _filename in  files:
            if _filename.startswith(stack_name) and _filename.endswith(".tar.gz"):
                filename = os.path.join("stacks", stack_name, _filename)
                filepath = os.path.join(root, _filename)
                upload(filename, filepath)
        


if __name__ == "__main__":
    upload_list(sys.argv[1], sys.argv[2])