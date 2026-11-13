#!/usr/bin/env python3
"""Report or delete build-request tags whose stack directory no longer exists.

Dry-run is the default. Confirmation requires GITHUB_TOKEN, accepts an
already-absent ref as success, and verifies every selected ref after deletion.
The optional audit is a JSON list with one entry per selected ref.
"""

import argparse
import json
import os
import re
import sys
from urllib.parse import quote

import requests


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STACKS_DIR = os.path.join(ROOT, "stacks")
API_ROOT = "https://api.github.com/repos/drycc/stacks"
TAG_REF = re.compile(r"refs/tags/([a-z0-9][a-z0-9_-]*)@([^@/\s]+)")
PAGE_SIZE = 100


class CleanupError(Exception):
    """A GitHub or local audit failure that must make the run non-zero."""


def obsolete_tag_refs(refs, current_stacks):
    """Return sorted, unique request-tag refs for absent stack directories."""
    current_stacks = frozenset(current_stacks)
    selected = set()
    for ref in refs:
        if not isinstance(ref, str):
            continue
        match = TAG_REF.fullmatch(ref)
        if match is not None and match.group(1) not in current_stacks:
            selected.add(ref)
    return sorted(selected)


def current_stack_names(stacks_dir=STACKS_DIR):
    """Read every current stack directory; OSS contents are irrelevant."""
    return {
        name for name in os.listdir(stacks_dir)
        if os.path.isdir(os.path.join(stacks_dir, name))
    }


def github_headers(token):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "drycc-stacks-obsolete-tag-cleanup",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


def list_tag_refs(session, headers):
    """List every tag ref, stopping when GitHub provides no next page."""
    refs = []
    page = 1
    while True:
        response = session.get(
            API_ROOT + "/git/refs/tags",
            params={"per_page": PAGE_SIZE, "page": page},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise CleanupError("GitHub tag listing was not a JSON list")
        for item in payload:
            if not isinstance(item, dict) or not isinstance(item.get("ref"), str):
                raise CleanupError("GitHub tag listing contained an invalid ref")
            refs.append(item["ref"])
        if not response.links.get("next"):
            return refs
        page += 1


def cleanup(confirm, session, headers, stacks_dir=STACKS_DIR):
    """Run one cleanup pass and return (audit entries, unexpected errors)."""
    refs = list_tag_refs(session, headers)
    candidates = obsolete_tag_refs(refs, current_stack_names(stacks_dir))
    for ref in candidates:
        print(ref)

    if not confirm:
        return [{"ref": ref, "action": "would-delete"} for ref in candidates], []
    if not candidates:
        return [], []

    audit = []
    errors = []
    for ref in candidates:
        entry = {"ref": ref}
        audit.append(entry)
        try:
            response = session.delete(
                API_ROOT + "/git/" + quote(ref, safe="/@"),
                headers=headers,
                timeout=30,
            )
            if response.status_code == 404:
                entry["action"] = "already-absent"
                print("already absent " + ref)
            else:
                response.raise_for_status()
                if response.status_code != 204:
                    raise CleanupError(
                        "unexpected delete status %d" % response.status_code
                    )
                entry["action"] = "deleted"
                print("deleted " + ref)
        except Exception as exc:  # noqa: BLE001 - finish independent deletions
            entry["action"] = "error"
            entry["error"] = str(exc)
            errors.append("%s: %s" % (ref, exc))

    try:
        remaining = set(list_tag_refs(session, headers)).intersection(candidates)
    except Exception as exc:  # noqa: BLE001 - retain partial deletion audit
        for entry in audit:
            entry["verification_error"] = str(exc)
        errors.append("verification failed: %s" % exc)
        return audit, errors

    for entry in audit:
        is_absent = entry["ref"] not in remaining
        entry["verified_absent"] = is_absent
        if not is_absent:
            entry.setdefault("error", "ref still present after cleanup")
            errors.append("%s: ref still present after cleanup" % entry["ref"])
    return audit, errors


def write_audit(path, audit):
    with open(path, "w", encoding="utf-8") as audit_file:
        json.dump(audit, audit_file, indent=2)
        audit_file.write("\n")


def main(argv=None, session=None, stacks_dir=STACKS_DIR):
    parser = argparse.ArgumentParser(
        description="Delete build-request tags for stacks absent from this checkout.",
    )
    parser.add_argument("--confirm", action="store_true", help="delete selected remote refs")
    parser.add_argument("--audit", help="write the per-ref JSON audit list to PATH")
    args = parser.parse_args(argv)

    if session is None:
        session = requests
    token = os.environ.get("GITHUB_TOKEN")
    audit = []
    status = 0
    try:
        if args.confirm and not token:
            raise CleanupError("GITHUB_TOKEN is required with --confirm")
        audit, errors = cleanup(
            confirm=args.confirm,
            session=session,
            headers=github_headers(token),
            stacks_dir=stacks_dir,
        )
        for error in errors:
            print("cleanup_obsolete_tags: " + error, file=sys.stderr)
        if errors:
            status = 1
    except Exception as exc:  # noqa: BLE001 - CLI maps unexpected errors to failure
        print("cleanup_obsolete_tags: %s" % exc, file=sys.stderr)
        status = 1

    if args.audit:
        try:
            write_audit(args.audit, audit)
        except Exception as exc:  # noqa: BLE001 - audit failure must be visible
            print("cleanup_obsolete_tags: cannot write audit: %s" % exc, file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
