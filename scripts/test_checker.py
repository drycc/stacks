import importlib.util
import re
import unittest
from pathlib import Path


CHECKER_PATH = Path(__file__).with_name("checker.py")


def load_checker():
    spec = importlib.util.spec_from_file_location("checker", CHECKER_PATH)
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    return checker


class JqTagPatternTest(unittest.TestCase):
    def setUp(self):
        self.pattern = load_checker().repo_info_table["jq"]["match"]

    def test_matches_stable_jq_tags(self):
        stable_tags = [
            "jq-1.6",
            "jq-1.7",
            "jq-1.7.1",
            "jq-1.8.0",
            "jq-1.8.1",
            "jq-1.8.2",
        ]
        for tag in stable_tags:
            with self.subTest(tag=tag):
                self.assertIsNotNone(re.fullmatch(self.pattern, tag))

    def test_rejects_unstable_or_malformed_jq_tags(self):
        unstable_tags = [
            "jq-1.7rc1",
            "jq-1.7rc2",
            "jq-1.8.2rc1",
            "jq-1.7.",
            "jq-1.8.2.1",
            "1.8.2",
        ]
        for tag in unstable_tags:
            with self.subTest(tag=tag):
                self.assertIsNone(re.fullmatch(self.pattern, tag))


if __name__ == "__main__":
    unittest.main()
