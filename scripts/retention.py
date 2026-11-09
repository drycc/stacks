#!/usr/bin/env python3
"""Generate the retention list consumed by cleaner.py.

Dynamic rules come from install-stack commands in Dockerfiles belonging to
an explicit set of GitHub repositories. Static rules are merged as additive
protection. A known stack with an unresolved version is protected wholesale;
GitHub or parsing failures abort before a new output file is installed.
"""

import argparse
import os
import re
import shlex
import sys
import tempfile
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from cleaner import STACK_NAME, load_retention_list

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_RETENTION_REPO = os.path.join(ROOT, "retention-repo.txt")
DEFAULT_RETENTION_LIST = os.path.join(ROOT, "retention-list.txt")
API_ROOT = "https://api.github.com"
RAW_ROOT = "https://raw.githubusercontent.com"
REPO_NAME = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
VERSION_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+~-]*")
VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")
SHELL_SEPARATORS = {"&&", "||", ";", "|"}


class RetentionError(Exception):
    """A source or parsing error that must prevent OSS cleanup."""


class GithubClient:
    """Small GitHub HTTP client with bounded retries and safe errors."""

    def __init__(self, token=None, timeout=30, session=None):
        self.timeout = timeout
        self.session = session or requests.Session()
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "drycc-stacks-retention",
        }
        if token:
            self.headers["Authorization"] = "Bearer " + token
        if session is None:
            retry = Retry(
                total=3,
                connect=3,
                read=3,
                status=3,
                backoff_factor=0.5,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset(["GET"]),
                respect_retry_after_header=True,
            )
            self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _get(self, url, params=None):
        try:
            response = self.session.get(
                url, params=params, headers=self.headers, timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise RetentionError(f"GitHub request failed: {url}: {exc}") from exc
        if response.status_code != 200:
            detail = response.text[:200].replace("\n", " ")
            raise RetentionError(
                f"GitHub request failed ({response.status_code}): {url}: {detail}"
            )
        return response

    def get_json(self, path, params=None):
        response = self._get(API_ROOT + path, params=params)
        try:
            return response.json()
        except ValueError as exc:
            raise RetentionError(f"GitHub returned invalid JSON: {path}") from exc

    def get_text(self, repo, sha, path):
        url = "%s/%s/%s/%s" % (
            RAW_ROOT, quote(repo, safe="/"), quote(sha, safe=""), quote(path, safe="/"),
        )
        return self._get(url).text


def parse_repo_list(lines):
    """Read owner/repository entries, rejecting an empty dynamic source set."""
    repos = []
    for lineno, raw in enumerate(lines, 1):
        entry = raw.strip()
        if not entry or entry.startswith("#"):
            continue
        if not REPO_NAME.fullmatch(entry):
            raise RetentionError(f"invalid repository at line {lineno}: {entry}")
        if entry not in repos:
            repos.append(entry)
    if not repos:
        raise RetentionError("no retention source repositories configured")
    return repos


def _logical_lines(text):
    """Yield (line number, logical Dockerfile instruction) pairs."""
    pending = ""
    start_line = 1
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            # Docker comments are discarded before continuations are joined;
            # retaining one here would hide every following shell token.
            continue
        if not pending:
            start_line = lineno
        pending += (" " if pending else "") + line
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        yield start_line, pending
        pending = ""
    if pending:
        yield start_line, pending


def _parse_variables(tokens, variables):
    if not tokens:
        return
    assignments = []
    if "=" not in tokens[0] and len(tokens) > 1:
        # Legacy ENV key value form. ARG key without a default is handled by
        # the single-token branch below and therefore remains unresolved.
        assignments.append((tokens[0], " ".join(tokens[1:])))
    else:
        for token in tokens:
            if "=" in token:
                name, value = token.split("=", 1)
                assignments.append((name, value))
            else:
                assignments.append((token, None))
    # Docker evaluates definitions using the environment that existed before
    # this instruction; later redefinitions must not retroactively alter them.
    expanded = []
    for name, value in assignments:
        if value is not None:
            value = _expand(value, variables)
            if "$" in value:
                # Unknown base/stage values stay tainted. A later assignment
                # must not rewrite the meaning of an earlier ENV/ARG definition.
                value = None
        expanded.append((name, value))
    variables.update(expanded)


def _expand(value, variables):
    for _ in range(20):
        def replace(match):
            name = match.group(1) or match.group(2)
            replacement = variables.get(name)
            return match.group(0) if replacement is None else replacement

        expanded = VARIABLE.sub(replace, value)
        if expanded == value:
            break
        value = expanded
    return value


def parse_dockerfile(text, source="Dockerfile"):
    """Return (whole stacks, exact version pins) from install-stack commands."""
    variables = {}
    stacks = set()
    versions = set()
    for lineno, line in _logical_lines(text):
        try:
            tokens = shlex.split(line, comments=True, posix=True)
        except ValueError as exc:
            raise RetentionError(f"cannot parse {source}:{lineno}: {exc}") from exc
        if not tokens:
            continue
        instruction = tokens[0].upper()
        if instruction == "FROM":
            # ARG/ENV declarations are stage-scoped for RUN commands. Values
            # inherited only from an image are unknown, so later use falls
            # back to whole-stack protection instead of guessing an exact pin.
            variables = {}
            continue
        if instruction in ("ARG", "ENV"):
            _parse_variables(tokens[1:], variables)
            continue
        if instruction != "RUN":
            continue
        for index, token in enumerate(tokens):
            if token != "install-stack":
                continue
            if index + 2 >= len(tokens) or tokens[index + 2] in SHELL_SEPARATORS:
                raise RetentionError(f"incomplete install-stack at {source}:{lineno}")
            stack = tokens[index + 1]
            raw_version = tokens[index + 2].rstrip(";")
            if not raw_version:
                raise RetentionError(f"incomplete install-stack at {source}:{lineno}")
            if not STACK_NAME.fullmatch(stack):
                raise RetentionError(f"invalid install-stack name at {source}:{lineno}: {stack}")
            version = _expand(raw_version, variables)
            if VERSION_NAME.fullmatch(version):
                versions.add((stack, version))
            else:
                # A missing build argument or unsupported shell expression must
                # increase protection, never silently remove it.
                stacks.add(stack)
    return stacks, versions


def merge_retention_rules(static_stacks, static_versions, dynamic_stacks, dynamic_versions):
    """Union both sources; whole-stack protection supersedes all its pins."""
    stacks = set(static_stacks) | set(dynamic_stacks)
    versions = {
        (stack, version)
        for stack, version in set(static_versions) | set(dynamic_versions)
        if stack not in stacks
    }
    return stacks, versions


def _is_dockerfile(path):
    # Test images consume OSS stacks too: Dockerfile.test and Dockerfiles under
    # test directories intentionally contribute the same retention protection.
    name = path.rsplit("/", 1)[-1].lower()
    return name == "dockerfile" or name.startswith("dockerfile.") or name.endswith(".dockerfile")


def fetch_repo_rules(repo, client):
    """Fetch and parse every Dockerfile at one immutable repository SHA."""
    try:
        metadata = client.get_json(f"/repos/{repo}")
        branch = metadata["default_branch"]
        commit = client.get_json(f"/repos/{repo}/commits/{quote(branch, safe='')}")
        sha = commit["sha"]
        tree = client.get_json(f"/repos/{repo}/git/trees/{sha}", params={"recursive": "1"})
    except (KeyError, TypeError) as exc:
        raise RetentionError(f"invalid GitHub metadata for {repo}") from exc
    if not isinstance(tree, dict) or not isinstance(tree.get("tree"), list):
        raise RetentionError(f"invalid GitHub tree for {repo}@{sha}")
    if tree.get("truncated"):
        raise RetentionError(f"GitHub tree is truncated for {repo}@{sha}")
    entries = []
    for entry in tree["tree"]:
        if not isinstance(entry, dict) \
                or not isinstance(entry.get("type"), str) \
                or not isinstance(entry.get("path"), str):
            raise RetentionError(f"invalid GitHub tree entry for {repo}@{sha}")
        if entry["type"] == "blob" and _is_dockerfile(entry["path"]):
            entries.append(entry)
    stacks = set()
    versions = set()
    for entry in entries:
        path = entry["path"]
        text = client.get_text(repo, sha, path)
        file_stacks, file_versions = parse_dockerfile(
            text, source=f"{repo}@{sha}:{path}",
        )
        stacks.update(file_stacks)
        versions.update(file_versions)
    report = f"{repo}@{sha}: {len(entries)} Dockerfile(s)"
    return stacks, versions, report


def generate_retention(repos, static_stacks, static_versions, client):
    """Generate dynamic rules and merge them with static protection."""
    if not repos:
        raise RetentionError("no retention source repositories configured")
    dynamic_stacks = set()
    dynamic_versions = set()
    reports = []
    for repo in repos:
        stacks, versions, report = fetch_repo_rules(repo, client)
        dynamic_stacks.update(stacks)
        dynamic_versions.update(versions)
        reports.append(report)
    stacks, versions = merge_retention_rules(
        static_stacks, static_versions, dynamic_stacks, dynamic_versions,
    )
    return stacks, versions, reports


def render_retention_list(stacks, versions, reports):
    lines = ["# Generated by scripts/retention.py; do not edit."]
    lines.extend("# " + report for report in reports)
    lines.append("")
    lines.extend(sorted(stacks))
    lines.extend(f"{stack}=={version}" for stack, version in sorted(versions))
    return "\n".join(lines) + "\n"


def _read_lines(path):
    with open(path, encoding="utf-8") as source:
        return source.readlines()


def _write_atomic(path, content):
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=parent, prefix=".retention-", delete=False,
        ) as output:
            temporary = output.name
            output.write(content)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None, client=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repos", default=DEFAULT_RETENTION_REPO,
                        help="repository list (default: retention-repo.txt)")
    parser.add_argument("--static", dest="static_list", default=DEFAULT_RETENTION_LIST,
                        help="static retention list (default: retention-list.txt)")
    parser.add_argument("--output", required=True, help="generated retention list path")
    args = parser.parse_args(argv)
    try:
        repos = parse_repo_list(_read_lines(args.repos))
        static_stacks, static_versions = load_retention_list(args.static_list)
        github = client or GithubClient(token=os.environ.get("GITHUB_TOKEN"))
        stacks, versions, reports = generate_retention(
            repos, static_stacks, static_versions, github,
        )
        content = render_retention_list(stacks, versions, reports)
        _write_atomic(args.output, content)
    except (OSError, ValueError, RetentionError) as exc:
        print(f"retention: error: {exc}", file=sys.stderr)
        return 1
    for report in reports:
        print("retention: " + report, file=sys.stderr)
    print(
        f"retention: wrote {args.output}: {len(stacks)} stack rule(s), "
        f"{len(versions)} version pin(s)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
