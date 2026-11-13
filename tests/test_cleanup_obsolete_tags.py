"""Tests for idempotent cleanup of tags belonging to removed stacks.

All GitHub traffic is served by FakeGithubSession; no test performs network or
OSS operations. Run: PYTHONPATH=tests .venv/bin/python -m unittest -v
 test_cleanup_obsolete_tags
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock
from urllib.parse import unquote, urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import cleanup_obsolete_tags  # noqa: E402


API_ROOT = "https://api.github.com/repos/drycc/stacks"


class FakeResponse:
    def __init__(self, payload, status_code=200, links=None):
        self.payload = payload
        self.status_code = status_code
        self.links = links or {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http %d" % self.status_code)


class FakeGithubSession:
    """Stateful in-memory GitHub refs endpoint with strict request checks."""

    def __init__(self, refs=(), delete_statuses=None, keep_on_delete=(), paginate=True):
        self.refs = list(refs)
        self.delete_statuses = dict(delete_statuses or {})
        self.keep_on_delete = set(keep_on_delete)
        self.calls = []
        self.list_status = 200
        self.fail_verification = False
        self.paginate = paginate

    @staticmethod
    def _check_timeout(timeout):
        if timeout != 30:
            raise AssertionError("GitHub timeout must be 30, got %r" % timeout)

    def get(self, url, params=None, headers=None, timeout=None):
        self._check_timeout(timeout)
        self.calls.append(("GET", url, params, headers, timeout))
        if url != API_ROOT + "/git/refs/tags":
            raise AssertionError("unexpected GET " + url)
        list_count = sum(call[0] == "GET" for call in self.calls)
        status = 500 if self.fail_verification and list_count > 1 else self.list_status
        if status != 200:
            return FakeResponse({"message": "list failed"}, status)
        if params is None or params.get("per_page") != 100 or params.get("page") is None:
            raise AssertionError("tag listing must use numbered 100-item pages")
        if not self.paginate:
            if list_count > 1:
                raise AssertionError("an unpaginated response must not be requested again")
            return FakeResponse([{"ref": ref} for ref in self.refs])
        page = params["page"]
        start = (page - 1) * 100
        end = start + 100
        payload = [{"ref": ref} for ref in self.refs[start:end]]
        links = {}
        if end < len(self.refs):
            links["next"] = {"url": API_ROOT + "/git/refs/tags?page=%d" % (page + 1)}
        return FakeResponse(payload, links=links)

    def delete(self, url, headers=None, timeout=None):
        self._check_timeout(timeout)
        self.calls.append(("DELETE", url, None, headers, timeout))
        prefix = API_ROOT + "/git/"
        if not url.startswith(prefix):
            raise AssertionError("unexpected DELETE " + url)
        # Model an HTTP server: fragments are not sent, then the path is
        # percent-decoded once before GitHub resolves the ref.
        path = urlsplit(url).path
        path_prefix = urlsplit(API_ROOT).path + "/git/"
        ref = unquote(path[len(path_prefix):])
        status = self.delete_statuses.get(ref, 204)
        if status in (204, 404) and ref not in self.keep_on_delete:
            self.refs = [candidate for candidate in self.refs if candidate != ref]
        return FakeResponse({}, status)

    def deletes(self):
        return [call for call in self.calls if call[0] == "DELETE"]


class ObsoleteTagRefsTest(unittest.TestCase):
    def test_selects_only_valid_absent_stack_tags(self):
        refs = [
            "refs/tags/removed@1.2.3",
            "refs/tags/current@9.9.9",
            "refs/tags/another_removed@v2",
            "refs/heads/removed@4.5.6",
            "removed@1.0.0",
            "refs/tags/removed@",
            "refs/tags/@1.0.0",
            "refs/tags/removed@1@2",
            "refs/tags/removed/extra@1.0.0",
            "refs/tags/Removed@1.0.0",
            "refs/tags/release-1.0.0",
        ]
        self.assertEqual(
            cleanup_obsolete_tags.obsolete_tag_refs(refs, {"current"}),
            ["refs/tags/another_removed@v2", "refs/tags/removed@1.2.3"],
        )

    def test_existing_stack_is_protected_without_any_oss_state(self):
        refs = ["refs/tags/current@0.0.1", "refs/tags/removed@0.0.1"]
        with mock.patch.dict(os.environ, {
            "OSS_ENDPOINT": "",
            "OSS_ACCESS_KEY_ID": "",
            "OSS_ACCESS_KEY_SECRET": "",
        }):
            self.assertEqual(
                cleanup_obsolete_tags.obsolete_tag_refs(refs, {"current"}),
                ["refs/tags/removed@0.0.1"],
            )


class TagListingTest(unittest.TestCase):
    def test_paginates_all_tag_refs_with_thirty_second_timeouts(self):
        refs = ["refs/tags/current@%03d" % number for number in range(100)]
        refs.append("refs/tags/removed@1.0.0")
        session = FakeGithubSession(refs)

        self.assertEqual(cleanup_obsolete_tags.list_tag_refs(session, {}), refs)
        gets = [call for call in session.calls if call[0] == "GET"]
        self.assertEqual([call[2]["page"] for call in gets], [1, 2])
        self.assertTrue(all(call[2]["per_page"] == 100 for call in gets))
        self.assertTrue(all(call[4] == 30 for call in gets))

    def test_unpaginated_full_response_without_next_link_is_not_repeated(self):
        refs = ["refs/tags/current@%03d" % number for number in range(101)]
        session = FakeGithubSession(refs, paginate=False)

        self.assertEqual(cleanup_obsolete_tags.list_tag_refs(session, {}), refs)
        gets = [call for call in session.calls if call[0] == "GET"]
        self.assertEqual(len(gets), 1)


class CleanupCliTest(unittest.TestCase):
    def setUp(self):
        self._orig_token = os.environ.get("GITHUB_TOKEN")
        os.environ["GITHUB_TOKEN"] = "test-token"
        self.tmp = tempfile.TemporaryDirectory()
        os.mkdir(os.path.join(self.tmp.name, "current"))

    def tearDown(self):
        self.tmp.cleanup()
        if self._orig_token is None:
            os.environ.pop("GITHUB_TOKEN", None)
        else:
            os.environ["GITHUB_TOKEN"] = self._orig_token

    def run_cli(self, session, *args):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = cleanup_obsolete_tags.main(
                list(args), session=session, stacks_dir=self.tmp.name,
            )
        return rc, stdout.getvalue(), stderr.getvalue()

    def audit_path(self):
        return os.path.join(self.tmp.name, "audit.json")

    def read_audit(self):
        with open(self.audit_path(), encoding="utf-8") as audit_file:
            return json.load(audit_file)

    def test_default_dry_run_prints_candidates_audits_and_never_deletes(self):
        session = FakeGithubSession([
            "refs/tags/current@1.0.0",
            "refs/tags/removed@1.0.0",
            "refs/tags/unrelated",
        ])

        rc, stdout, stderr = self.run_cli(session, "--audit", self.audit_path())

        self.assertEqual(rc, 0, stderr)
        self.assertEqual(stdout, "refs/tags/removed@1.0.0\n")
        self.assertEqual(session.deletes(), [])
        self.assertEqual(len([call for call in session.calls if call[0] == "GET"]), 1)
        self.assertEqual(self.read_audit(), [
            {"ref": "refs/tags/removed@1.0.0", "action": "would-delete"},
        ])
        self.assertEqual(session.refs, [
            "refs/tags/current@1.0.0", "refs/tags/removed@1.0.0", "refs/tags/unrelated",
        ])

    def test_confirm_requires_a_token_before_any_request(self):
        os.environ.pop("GITHUB_TOKEN", None)
        session = FakeGithubSession(["refs/tags/removed@1.0.0"])

        rc, _, stderr = self.run_cli(session, "--confirm")

        self.assertNotEqual(rc, 0)
        self.assertIn("GITHUB_TOKEN", stderr)
        self.assertEqual(session.calls, [])

    def test_confirm_deletes_through_git_ref_and_verifies_absence(self):
        session = FakeGithubSession([
            "refs/tags/current@1.0.0", "refs/tags/removed@1.0.0",
        ])

        rc, stdout, stderr = self.run_cli(
            session, "--confirm", "--audit", self.audit_path(),
        )

        self.assertEqual(rc, 0, stderr)
        self.assertIn("deleted refs/tags/removed@1.0.0", stdout)
        self.assertEqual(
            [call[1] for call in session.deletes()],
            [API_ROOT + "/git/refs/tags/removed@1.0.0"],
        )
        self.assertEqual(len([call for call in session.calls if call[0] == "GET"]), 2)
        self.assertEqual(session.refs, ["refs/tags/current@1.0.0"])
        self.assertEqual(self.read_audit(), [
            {
                "ref": "refs/tags/removed@1.0.0",
                "action": "deleted",
                "verified_absent": True,
            },
        ])
        self.assertTrue(all(call[4] == 30 for call in session.calls))

    def test_confirm_url_escapes_refs_and_verifies_absence(self):
        cases = (
            ("fragment", "refs/tags/removed@1#2", "refs/tags/removed@1%232"),
            (
                "literal-percent",
                "refs/tags/removed@100%2Fkeep",
                "refs/tags/removed@100%252Fkeep",
            ),
        )
        for name, ref, encoded_ref in cases:
            with self.subTest(name=name):
                session = FakeGithubSession([ref])

                rc, _, stderr = self.run_cli(
                    session, "--confirm", "--audit", self.audit_path(),
                )

                self.assertEqual(
                    [call[1] for call in session.deletes()],
                    [API_ROOT + "/git/" + encoded_ref],
                )
                self.assertEqual(rc, 0, stderr)
                self.assertEqual(session.refs, [])
                self.assertEqual(
                    len([call for call in session.calls if call[0] == "GET"]), 2,
                )
                self.assertEqual(self.read_audit(), [
                    {"ref": ref, "action": "deleted", "verified_absent": True},
                ])

    def test_already_absent_404_is_an_idempotent_success(self):
        ref = "refs/tags/removed@1.0.0"
        session = FakeGithubSession([ref], delete_statuses={ref: 404})

        rc, stdout, stderr = self.run_cli(
            session, "--confirm", "--audit", self.audit_path(),
        )

        self.assertEqual(rc, 0, stderr)
        self.assertIn("already absent " + ref, stdout)
        self.assertEqual(self.read_audit(), [
            {"ref": ref, "action": "already-absent", "verified_absent": True},
        ])

    def test_partial_failure_is_auditable_and_remaining_work_can_be_rerun(self):
        failed = "refs/tags/removed-a@1.0.0"
        deleted = "refs/tags/removed-b@1.0.0"
        session = FakeGithubSession([failed, deleted], delete_statuses={failed: 500})

        rc, stdout, stderr = self.run_cli(
            session, "--confirm", "--audit", self.audit_path(),
        )

        self.assertNotEqual(rc, 0)
        self.assertEqual(len(session.deletes()), 2)
        self.assertIn("deleted " + deleted, stdout)
        self.assertIn(failed, stderr)
        self.assertEqual(self.read_audit(), [
            {
                "ref": failed,
                "action": "error",
                "error": "http 500",
                "verified_absent": False,
            },
            {"ref": deleted, "action": "deleted", "verified_absent": True},
        ])

        session.delete_statuses.clear()
        rc, _, stderr = self.run_cli(session, "--confirm")
        self.assertEqual(rc, 0, stderr)
        self.assertEqual(session.refs, [])

    def test_final_verification_rejects_a_ref_that_still_exists(self):
        ref = "refs/tags/removed@1.0.0"
        session = FakeGithubSession([ref], keep_on_delete={ref})

        rc, _, stderr = self.run_cli(
            session, "--confirm", "--audit", self.audit_path(),
        )

        self.assertNotEqual(rc, 0)
        self.assertIn("still present", stderr)
        self.assertEqual(self.read_audit(), [
            {
                "ref": ref,
                "action": "deleted",
                "verified_absent": False,
                "error": "ref still present after cleanup",
            },
        ])

    def test_verification_error_preserves_successful_delete_results(self):
        ref = "refs/tags/removed@1.0.0"
        session = FakeGithubSession([ref])
        session.fail_verification = True

        rc, stdout, stderr = self.run_cli(
            session, "--confirm", "--audit", self.audit_path(),
        )

        self.assertNotEqual(rc, 0)
        self.assertIn("deleted " + ref, stdout)
        self.assertIn("verification", stderr)
        self.assertEqual(self.read_audit(), [
            {
                "ref": ref,
                "action": "deleted",
                "verification_error": "http 500",
            },
        ])

    def test_initial_list_error_is_nonzero_and_writes_an_empty_audit(self):
        session = FakeGithubSession(["refs/tags/removed@1.0.0"])
        session.list_status = 500

        rc, _, stderr = self.run_cli(
            session, "--confirm", "--audit", self.audit_path(),
        )

        self.assertNotEqual(rc, 0)
        self.assertIn("http 500", stderr)
        self.assertEqual(session.deletes(), [])
        self.assertEqual(self.read_audit(), [])


if __name__ == "__main__":
    unittest.main()
