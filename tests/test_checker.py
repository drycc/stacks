"""Pure version-discovery tests for scripts/checker.py.

normalize_version extracts the stack version from an upstream tag name;
discover_candidates lists upstream release candidates for a stack without
ever creating tags or issues in drycc/stacks.

Run: .venv/bin/python -m unittest discover -s tests -p 'test_checker.py' -v
"""

import os
import re
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import checker  # noqa: E402


GITHUB_STACK = "fakegithub"
GITHUB_INFO = {
    "name": "fake",
    "type": "github",
    "owner": "fakeorg",
    "match": r"^v?[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
}
COMMIT_URL = "https://api.github.com/repos/fakeorg/fake/commits/c3"


def edge(name, oid, date=None):
    """Build a GraphQL tag edge; without a date the tag is lightweight and
    the commit date must be resolved via a REST lookup."""
    target = {"oid": oid}
    if date is not None:
        target["tagger"] = {"date": date}
    return {"node": {"name": name, "target": target}}


DEFAULT_EDGES = [
    edge("v1.2.4", "a1", "2026-11-04T10:00:00Z"),  # matched, annotated
    edge("nightly", "b2", "2026-11-03T09:00:00Z"),  # not matched by regex
    edge("v1.2.3", "c3"),  # matched, lightweight -> REST commit date
    edge("1.2.3", "d4", "2026-11-01T08:00:00Z"),  # matched, same version as above
    edge("v1.0.0", "e5", "2026-08-01T07:00:00Z"),  # matched, older than 7 days
]


class FakeResponse:
    def __init__(self, payload=None, text=""):
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class FakeSession:
    """Serves canned responses per URL and records every request."""

    def __init__(self, gets=None, posts=None):
        self.requests = []
        self._gets = gets or {}
        self._posts = posts or {}

    def get(self, url, **kwargs):
        self.requests.append(("GET", url))
        return FakeResponse(**self._gets[url])

    def post(self, url, **kwargs):
        self.requests.append(("POST", url))
        return FakeResponse(**self._posts[url])


class StrictRequests:
    """Stands in for the requests module: any call is a test failure."""

    def _fail(self, method, url):
        raise AssertionError("checker.requests.%s(%s) must not be called" % (method, url))

    def get(self, url, **kwargs):
        self._fail("get", url)

    def post(self, url, **kwargs):
        self._fail("post", url)


def graphql_response(edges):
    return {"payload": {"data": {"repository": {"refs": {"edges": edges}}}}}


def github_session(edges=DEFAULT_EDGES):
    return FakeSession(
        gets={COMMIT_URL: {"payload": {"commit": {"author": {"date": "2026-11-02T12:00:00Z"}}}}},
        posts={"https://api.github.com/graphql": graphql_response(edges)},
    )


class NormalizeVersionTest(unittest.TestCase):
    def test_normalizes_upstream_tag_names(self):
        cases = [
            ("v0.9.3", "0.9.3"),
            ("1.0.4", "1.0.4"),
            ("jq-1.8.2", "1.8.2"),
            ("OTP-29.1.1", "29.1.1"),
            ("release-1.31.8", "1.31.8"),
            ("v2.1.0-alpine", "2.1.0"),
        ]
        for tag_name, expected in cases:
            with self.subTest(tag_name=tag_name):
                self.assertEqual(checker.normalize_version(tag_name), expected)


class GithubDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self._orig_table = dict(checker.repo_info_table)
        self._orig_requests = checker.requests
        checker.repo_info_table[GITHUB_STACK] = dict(GITHUB_INFO)
        checker.requests = StrictRequests()

    def tearDown(self):
        checker.repo_info_table.clear()
        checker.repo_info_table.update(self._orig_table)
        checker.requests = self._orig_requests

    def test_filters_unmatched_tags_and_keeps_order_and_dates(self):
        candidates = checker.discover_candidates(GITHUB_STACK, session=github_session())
        self.assertEqual(
            candidates,
            [
                {
                    "stack": GITHUB_STACK,
                    "version": "1.2.4",
                    "upstream": "v1.2.4",
                    "date": datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc),
                },
                {
                    "stack": GITHUB_STACK,
                    "version": "1.2.3",
                    "upstream": "v1.2.3",
                    "date": datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc),
                },
                {
                    "stack": GITHUB_STACK,
                    "version": "1.0.0",
                    "upstream": "v1.0.0",
                    "date": datetime(2026, 8, 1, 7, 0, tzinfo=timezone.utc),
                },
            ],
        )

    def test_dedupes_tags_that_normalize_to_the_same_version(self):
        candidates = checker.discover_candidates(GITHUB_STACK, session=github_session())
        versions = [candidate["version"] for candidate in candidates]
        self.assertEqual(versions, ["1.2.4", "1.2.3", "1.0.0"])

    def test_discovers_tags_older_than_seven_days(self):
        edges = [edge("v1.0.0", "x1", "2024-01-01T00:00:00Z")]
        candidates = checker.discover_candidates(GITHUB_STACK, session=github_session(edges))
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["version"], "1.0.0")

    def test_does_not_touch_drycc_stacks(self):
        session = github_session()
        checker.discover_candidates(GITHUB_STACK, session=session)
        urls = [url for _, url in session.requests]
        self.assertTrue(urls)
        for url in urls:
            self.assertNotIn("drycc/stacks", url)


class UrlDiscoveryTest(unittest.TestCase):
    URL_STACK = "fakeurl"
    URL_INFO = {
        "url": "https://example.com/downloads",
        "type": "url",
        "search": r"example-[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}\.tar\.gz",
        "version": r"[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}",
    }
    HTML = (
        "links: example-2.0.0.tar.gz example-1.9.1.tar.gz "
        "dup: example-1.9.1.tar.gz skip: example-nightly.tar.gz skip: example-2.0.tar.gz"
    )

    def setUp(self):
        self._orig_table = dict(checker.repo_info_table)
        self._orig_requests = checker.requests
        checker.repo_info_table[self.URL_STACK] = dict(self.URL_INFO)
        checker.requests = StrictRequests()

    def tearDown(self):
        checker.repo_info_table.clear()
        checker.repo_info_table.update(self._orig_table)
        checker.requests = self._orig_requests

    def test_discovers_versions_from_page(self):
        session = FakeSession(gets={self.URL_INFO["url"]: {"text": self.HTML}})
        candidates = checker.discover_candidates(self.URL_STACK, session=session)
        self.assertEqual(
            {candidate["version"] for candidate in candidates},
            {"2.0.0", "1.9.1"},
        )
        for candidate in candidates:
            self.assertEqual(candidate["stack"], self.URL_STACK)
            self.assertEqual(candidate["upstream"], candidate["version"])
            self.assertIsNone(candidate["date"])


class RepoInfoTableTest(unittest.TestCase):
    def test_covers_every_stack_directory(self):
        stacks_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "stacks"
        )
        stack_dirs = {
            name
            for name in os.listdir(stacks_dir)
            if os.path.isdir(os.path.join(stacks_dir, name))
        }
        # main() iterates the stack directories, so every directory needs an
        # entry; an entry without a directory is dead configuration and an
        # entry is missing a stack silently fails discovery, so require an
        # exact match.
        self.assertEqual(stack_dirs, set(checker.repo_info_table.keys()))


class JqTagPatternTest(unittest.TestCase):
    """jq upstream tags look like jq-1.7.1, with rc suffixes for
    pre-releases (jq-1.7rc1) and a plain semver shape since the jqlang
    move. The match pattern must accept the former and reject the
    latter, or rc tags would leak into the discovery candidates."""

    def setUp(self):
        self.pattern = checker.repo_info_table["jq"]["match"]

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


class VersionSeriesTest(unittest.TestCase):
    """The retention series drops only the final dot-separated component,
    so independently maintained tracks each get their own newest-N window."""

    def test_drops_the_last_component(self):
        cases = {
            "13.4": "13",
            "8.0.1": "8.0",
            "7.18.2": "7.18",
            "4.52": "4",
            "24.3.4.147": "24.3.4",
            "2023.07.18.21.05.38": "2023.07.18.21.05",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(checker.version_series(value), expected)

    def test_a_version_without_a_dot_is_its_own_series(self):
        self.assertEqual(checker.version_series("17"), "17")
        self.assertEqual(checker.version_series("23_2_5"), "23_2_5")


class RetentionKeepTest(unittest.TestCase):
    """retention_keep provides the shared semantic ordering: the nightly
    planner applies it to candidates newer than the current OSS boundary,
    and the cleaner applies it to existing versions. The planner's
    roll-forward rule guarantees cleanup never schedules a rebuild."""

    def test_keeps_the_newest_versions_by_semantic_order(self):
        kept = checker.retention_keep(["1.9.0", "1.10.0", "1.31.0", "1.8.0"], 3)
        self.assertEqual(kept, ["1.31.0", "1.10.0", "1.9.0"])

    def test_semantic_not_lexicographic_order(self):
        # lexicographic order ranks "1.9.0" above "1.10.0" and would keep
        # the old series while dropping the newest minor line
        kept = checker.retention_keep(["1.7.0", "1.8.0", "1.9.0", "1.10.0"], 3)
        self.assertEqual(kept, ["1.10.0", "1.9.0", "1.8.0"])

    def test_fewer_versions_than_the_count_keeps_everything(self):
        kept = checker.retention_keep(["4.9", "4.52"], 3)
        self.assertEqual(kept, ["4.52", "4.9"])

    def test_unparseable_versions_are_always_kept(self):
        # their age is unknown, so dropping them would be a guess
        kept = checker.retention_keep(["1.0.0", "not-a-version!", "0.9.0"], 1)
        self.assertEqual(kept, ["1.0.0", "not-a-version!"])

    def test_count_below_one_is_rejected(self):
        with self.assertRaises(ValueError):
            checker.retention_keep(["1.0.0"], 0)

    def test_default_retention_is_the_shared_constant(self):
        # DEFAULT_RETENTION is the planner default and the reference for
        # the cleaner's required -n value; it must stay a plain int so
        # both tools share one retention rule without extra configuration.
        self.assertIsInstance(checker.DEFAULT_RETENTION, int)
        self.assertEqual(checker.DEFAULT_RETENTION, 2)
        versions = ["1.0.%d" % i for i in range(8)]
        kept = checker.retention_keep(versions)
        self.assertEqual(len(kept), checker.DEFAULT_RETENTION)
        self.assertEqual(kept[0], "1.0.7")


class NoSideEffectsTest(unittest.TestCase):
    """checker.py is a pure discovery library.

    The nightly reconcile flow replaced the old checker that created
    drycc/stacks tags and "new build for ..." issues. Those mutation
    entry points must not grow back.
    """

    def test_has_no_drycc_mutation_entry_points(self):
        for name in (
            "create_github_tag",
            "create_github_issue",
            "check_github_version",
            "check_url_version",
            "main",
        ):
            with self.subTest(function=name):
                self.assertFalse(hasattr(checker, name))

    def test_module_is_not_runnable(self):
        self.assertIsNone(getattr(checker, "__main__", None))
        source = open(checker.__file__).read()
        self.assertNotIn('__name__ == "__main__"', source)

    def test_only_supported_types(self):
        for stack, info in checker.repo_info_table.items():
            with self.subTest(stack=stack):
                self.assertIn(info["type"], ("github", "url"))


if __name__ == "__main__":
    unittest.main()
