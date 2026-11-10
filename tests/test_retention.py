"""Tests for dynamic retention generation in scripts/retention.py.

Run: .venv/bin/python -m unittest discover -s tests -p 'test_retention.py' -v
"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

os.environ.setdefault("OSS_ACCESS_KEY_ID", "test-access-key-id")
os.environ.setdefault("OSS_ACCESS_KEY_SECRET", "test-access-key-secret")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import retention  # noqa: E402


class RepoListTest(unittest.TestCase):
    def test_reads_repositories_and_ignores_comments(self):
        self.assertEqual(
            retention.parse_repo_list([
                "# image sources\n",
                "drycc-addons/containers\n",
                "\n",
                "drycc/builder\n",
            ]),
            ["drycc-addons/containers", "drycc/builder"],
        )

    def test_rejects_anything_other_than_owner_slash_repository(self):
        with self.assertRaisesRegex(retention.RetentionError, "invalid repository"):
            retention.parse_repo_list(["https://github.com/drycc/builder\n"])

    def test_rejects_an_empty_source_list(self):
        with self.assertRaisesRegex(retention.RetentionError, "no retention source repositories"):
            retention.parse_repo_list(["# no sources configured\n", "\n"])


class DockerfileParseTest(unittest.TestCase):
    def test_resolves_arg_env_literal_and_composite_versions(self):
        stacks, versions = retention.parse_dockerfile(
            '''ARG JQ_VERSION="1.8.2"
ENV PG_MAJOR=18 \\
  PG_MINOR=4
ENV INI_FILE_VERSION="1.4.9"
RUN install-stack jq ${JQ_VERSION} && \\
  install-stack postgresql $PG_MAJOR.$PG_MINOR && \\
  install-stack ini-file $INI_FILE_VERSION
RUN install-stack wait-for-port 1.0.10
''',
            source="example/Dockerfile",
        )
        self.assertEqual(stacks, set())
        self.assertEqual(versions, {
            ("jq", "1.8.2"),
            ("postgresql", "18.4"),
            ("ini-file", "1.4.9"),
            ("wait-for-port", "1.0.10"),
        })

    def test_env_values_are_expanded_when_defined(self):
        _, versions = retention.parse_dockerfile(
            '''ENV PG_MAJOR=18 PG_MINOR=4
ENV PG_VERSION=$PG_MAJOR.$PG_MINOR
ENV PG_MINOR=5
RUN install-stack postgresql $PG_VERSION
'''
        )
        self.assertEqual(versions, {("postgresql", "18.4")})

    def test_variables_do_not_leak_between_build_stages(self):
        stacks, versions = retention.parse_dockerfile(
            '''FROM registry.example/base:first
ENV VERSION=1.8.2
FROM registry.example/base:second
RUN install-stack jq $VERSION
'''
        )
        self.assertEqual(stacks, {"jq"})
        self.assertEqual(versions, set())

    def test_unresolved_definition_cannot_be_revived_by_later_assignments(self):
        stacks, versions = retention.parse_dockerfile(
            '''FROM registry.example/base
ENV PG_VERSION=$PG_MAJOR.$PG_MINOR
ENV PG_MAJOR=18 PG_MINOR=4
RUN install-stack postgresql $PG_VERSION
'''
        )
        self.assertEqual(stacks, {"postgresql"})
        self.assertEqual(versions, set())

    def test_legacy_env_syntax_is_supported(self):
        _, versions = retention.parse_dockerfile(
            "ENV MC_VERSION 2023.07.18.21.05.38\nRUN install-stack mc $MC_VERSION\n"
        )
        self.assertEqual(versions, {("mc", "2023.07.18.21.05.38")})

    def test_trailing_shell_semicolon_is_not_part_of_the_version(self):
        stacks, versions = retention.parse_dockerfile(
            "RUN install-stack jq 1.8.2; install-stack yj 5.1.0;\n"
        )
        self.assertEqual(stacks, set())
        self.assertEqual(versions, {("jq", "1.8.2"), ("yj", "5.1.0")})

    def test_unresolved_versions_protect_the_whole_stack(self):
        stacks, versions = retention.parse_dockerfile(
            '''ARG EXTERNALLY_SUPPLIED_VERSION
RUN install-stack mysql $EXTERNALLY_SUPPLIED_VERSION && \\
  install-stack postgresql ${PG_VERSION:-18}
'''
        )
        self.assertEqual(stacks, {"mysql", "postgresql"})
        self.assertEqual(versions, set())

    def test_unknown_stack_names_are_not_filtered(self):
        _, versions = retention.parse_dockerfile(
            "RUN install-stack mariadb 11.0.2 && install-stack minio 2023.07.18.17.49.40\n"
        )
        self.assertEqual(versions, {
            ("mariadb", "11.0.2"),
            ("minio", "2023.07.18.17.49.40"),
        })

    def test_comments_do_not_create_rules(self):
        stacks, versions = retention.parse_dockerfile(
            "# RUN install-stack mysql 8.4.9\nFROM registry.example/base:latest\n"
        )
        self.assertEqual((stacks, versions), (set(), set()))

    def test_comment_only_lines_inside_continuations_do_not_hide_commands(self):
        stacks, versions = retention.parse_dockerfile(
            '''RUN install-stack jq 1.8.2 && \\
  # explain why yq is also needed
  install-stack yq 4.50.1
'''
        )
        self.assertEqual(stacks, set())
        self.assertEqual(versions, {("jq", "1.8.2"), ("yq", "4.50.1")})

    def test_malformed_install_stack_aborts_with_its_source(self):
        with self.assertRaisesRegex(retention.RetentionError, "broken/Dockerfile"):
            retention.parse_dockerfile(
                "RUN install-stack mysql\n", source="broken/Dockerfile"
            )


class DockerfileDiscoveryTest(unittest.TestCase):
    def test_test_dockerfiles_and_test_directories_are_included(self):
        for path in (
            "rootfs/Dockerfile.test",
            "Dockerfile.tests",
            "Dockerfile.integration-test",
            "test/Dockerfile",
            "tests/Dockerfile.build",
            "testing/Dockerfile",
        ):
            with self.subTest(path=path):
                self.assertTrue(retention._is_dockerfile(path))

    def test_production_dockerfile_variants_remain_included(self):
        for path in (
            "Dockerfile",
            "Dockerfile.build",
            "rootfs/Dockerfile.run",
            "Dockerfile.latest",
            "images/prod.dockerfile",
        ):
            with self.subTest(path=path):
                self.assertTrue(retention._is_dockerfile(path))


class MergeTest(unittest.TestCase):
    def test_whole_stack_rules_dominate_pins_and_static_rules_survive(self):
        stacks, versions = retention.merge_retention_rules(
            {"python"},
            {("legacy", "1.0"), ("mysql", "8.4.8")},
            {"mysql"},
            {("python", "3.12"), ("mysql", "8.4.9"), ("nginx", "1.31.8")},
        )
        self.assertEqual(stacks, {"python", "mysql"})
        self.assertEqual(versions, {("legacy", "1.0"), ("nginx", "1.31.8")})


class FakeGithubClient:
    def __init__(self, dockerfiles=None, error=None):
        self.dockerfiles = dockerfiles or {}
        self.error = error
        self.raw_requests = []

    def get_json(self, path, params=None):
        if self.error:
            raise self.error
        if path == "/repos/example/containers":
            return {"default_branch": "main"}
        if path == "/repos/example/containers/commits/main":
            return {"sha": "abc123"}
        if path == "/repos/example/containers/git/trees/abc123":
            entries = [
                {"type": "blob", "path": path, "sha": "blob-" + str(index)}
            for index, path in enumerate(self.dockerfiles)
            ]
            entries.append({"type": "blob", "path": "README.md", "sha": "blob-readme"})
            return {"truncated": False, "tree": entries}
        raise AssertionError("unexpected API path: " + path)

    def get_text(self, repo, sha, path):
        self.raw_requests.append((repo, sha, path))
        if path not in self.dockerfiles:
            raise AssertionError("unexpected raw path: " + path)
        return self.dockerfiles[path]


class GenerateTest(unittest.TestCase):
    def test_fetches_one_immutable_snapshot_and_merges_static_rules(self):
        client = FakeGithubClient({
            "containers/mysql/8.4/Dockerfile": (
                "ARG MYSQL_VERSION=8.4.9\nRUN install-stack mysql $MYSQL_VERSION\n"
            ),
            "Dockerfile.build": "RUN install-stack jq 1.8.2\n",
        })
        stacks, versions, reports = retention.generate_retention(
            ["example/containers"],
            {"python"},
            {("legacy", "1.0")},
            client,
        )
        self.assertEqual(stacks, {"python"})
        self.assertEqual(versions, {
            ("legacy", "1.0"),
            ("mysql", "8.4.9"),
            ("jq", "1.8.2"),
        })
        self.assertEqual(reports, ["example/containers@abc123: 2 Dockerfile(s)"])
        self.assertTrue(client.raw_requests)
        self.assertTrue(all(sha == "abc123" for _, sha, _ in client.raw_requests))

    def test_test_dockerfiles_contribute_retention_rules(self):
        client = FakeGithubClient({
            "rootfs/Dockerfile": "RUN install-stack python 3.15\n",
            "rootfs/Dockerfile.test": "RUN install-stack valkey 9.1.3\n",
            "tests/Dockerfile": "RUN install-stack gosu 1.19\n",
        })
        _, versions, reports = retention.generate_retention(
            ["example/containers"], set(), set(), client,
        )
        self.assertEqual(versions, {
            ("python", "3.15"),
            ("valkey", "9.1.3"),
            ("gosu", "1.19"),
        })
        self.assertEqual(reports, ["example/containers@abc123: 3 Dockerfile(s)"])

    def test_github_failure_does_not_return_partial_static_only_rules(self):
        client = FakeGithubClient(error=retention.RetentionError("github down"))
        with self.assertRaisesRegex(retention.RetentionError, "github down"):
            retention.generate_retention(["example/containers"], {"python"}, set(), client)

    def test_a_missing_tree_member_aborts_instead_of_producing_static_only_rules(self):
        client = FakeGithubClient()
        get_json = client.get_json

        def malformed_tree(path, params=None):
            if path == "/repos/example/containers/git/trees/abc123":
                return {}
            return get_json(path, params=params)

        client.get_json = malformed_tree
        with self.assertRaisesRegex(retention.RetentionError, "invalid GitHub tree"):
            retention.generate_retention(["example/containers"], {"python"}, set(), client)

    def test_cli_writes_the_final_list_with_source_provenance(self):
        client = FakeGithubClient({
            "Dockerfile": "RUN install-stack mysql 8.4.9\n",
        })
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "generated.txt")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                rc = retention.main([
                    "--repos", self._write(tmp, "repos.txt", "example/containers\n"),
                    "--static", self._write(tmp, "static.txt", "python\n"),
                    "--output", output,
                ], client=client)
            self.assertEqual(rc, 0, stderr.getvalue())
            with open(output, encoding="utf-8") as generated:
                text = generated.read()
            self.assertIn("# example/containers@abc123: 1 Dockerfile(s)", text)
            self.assertIn("python\n", text)
            self.assertIn("mysql==8.4.9\n", text)

    def test_cli_failure_leaves_an_existing_output_untouched(self):
        client = FakeGithubClient(error=retention.RetentionError("github down"))
        with tempfile.TemporaryDirectory() as tmp:
            output = self._write(tmp, "generated.txt", "previous-good-list\n")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                rc = retention.main([
                    "--repos", self._write(tmp, "repos.txt", "example/containers\n"),
                    "--static", self._write(tmp, "static.txt", "python\n"),
                    "--output", output,
                ], client=client)
            self.assertEqual(rc, 1)
            with open(output, encoding="utf-8") as generated:
                self.assertEqual(generated.read(), "previous-good-list\n")
            self.assertIn("github down", stderr.getvalue())

    @staticmethod
    def _write(directory, name, content):
        path = os.path.join(directory, name)
        with open(path, "w", encoding="utf-8") as output:
            output.write(content)
        return path


class GithubClientTest(unittest.TestCase):
    def test_http_errors_are_retention_errors_and_do_not_leak_the_token(self):
        response = mock.Mock(status_code=403, text="rate limited")
        session = mock.Mock()
        session.get.return_value = response
        client = retention.GithubClient(token="secret-token", session=session)
        with self.assertRaisesRegex(retention.RetentionError, "403") as caught:
            client.get_json("/repos/example/containers")
        self.assertNotIn("secret-token", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
