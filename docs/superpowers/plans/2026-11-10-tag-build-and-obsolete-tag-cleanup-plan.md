# Tag-driven builds and obsolete-resource cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build individual stack versions through `<stack>@<version>` tags, make cron schedule those tags instead of building, and reconcile obsolete tags and failure issues safely every day.

**Architecture:** Cron retains OSS planning and schedules unique Git refs. A tag workflow checks an exact normal-artifact predicate before and after building, retains successful tags, and deletes failed tags for a later retry. Independent daily utilities delete tags for removed stacks and reconcile open failure issues from current directories plus exact OSS state.

**Tech Stack:** Bash, Python 3, unittest, Woodpecker YAML, GitHub REST API, Aliyun OSS via oss2.

**Spec:** `docs/superpowers/specs/2026-11-10-tag-build-and-obsolete-tag-cleanup-design.md`

## Global Constraints

- Use only `<stack>@<version>`; no request-tag prefixes, architecture suffixes, Woodpecker status API, or distributed lock.
- Completion requires the exact key to exist as a normal, non-symlink OSS object before build, after upload, and during issue reconciliation.
- Success retains the tag and never creates another ref; genuine build/upload/verification failure always attempts tag deletion even if alert reporting fails.
- A success-side issue resolution error never deletes the tag; daily reconciliation retries it.
- Repeat failures comment on the existing exact-title issue; amd64 and arm64 issues remain independent.
- Removed stacks cancel open failure issues as `not_planned`; do not permanently delete issues or modify closed history.
- Existing stacks' tags are never deleted by obsolete-stack cleanup, regardless of OSS state.
- `RECONCILE_DRY_RUN` or `CLEANER_DRY_RUN` forbids OSS, ref, comment, and issue-state mutation.
- Leave `scripts/cleaner.py` and its retention algorithm unchanged.
- Do not run `git commit`, `git push`, or other git mutations without separate explicit user confirmation; checkpoints below are test/diff reviews, not automatic commits.

## Review Focus

- Symlink-only objects and zero-artifact uploads must never close an issue: Task 1 and Task 4 tests.
- Alert failure must still permit failure-tag deletion, while resolve failure retains it: Task 4 tests.
- Removed stacks cancel open issues, but existing stacks with missing/uncertain artifacts stay open: Task 6 tests.
- Duplicate refs, 404 deletion, and repeated cleanup must be idempotent: Tasks 2, 3, and 5 tests.
- Dry-run and OSS/GitHub errors must produce no mutation and must not be treated as success: Tasks 1, 5, and 6 tests.

---

### Task 1: Exact artifact predicate and enforced upload

**Files:**
- Modify: `scripts/checker.py`
- Modify: `scripts/storage.py`
- Modify: `scripts/reconcile.py` (only delegate `object_key` to the shared helper)
- Test: `tests/test_checker.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Produces: `checker.object_key(stack: str, version: str, arch: str, flavour: str) -> str`.
- Produces: `storage.artifact_exists(stack: str, version: str, arch: str, flavour: str, bucket=None) -> bool`; returns `False` for missing/symlink-only and raises on service errors.
- Produces CLI: `storage.py artifact-exists STACK VERSION [--arch ARCH|auto] [--flavour FLAVOUR|auto]`; exit 0 exists, 1 missing/symlink, 2 error.
- Produces: `storage.upload_list(stack_name, dist_dir) -> list[str]`; raises `ValueError` when no matching archive is found and returns uploaded keys otherwise.

- [ ] **Step 1: Write failing tests**

Add tests proving: the shared key layout matches the current layout; `artifact_exists` returns `True` only for an exact non-symlink match; another prefix, a symlink, or a missing key returns `False`; bucket errors propagate; `upload_list` raises `ValueError("no stack archives found")` on an empty stack directory. Add CLI tests for exit codes 0/1/2 and auto arch/flavour detection.

```python
self.assertFalse(storage.artifact_exists(
    "nginx", "1.31.8", "amd64", "debian-13",
    bucket=FakeBucket([FakeObject(key, type="Symlink")]),
))
```

- [ ] **Step 2: Run tests to verify RED**

Run: `.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`
Expected: new tests fail because the predicate/upload guard/CLI do not exist.

- [ ] **Step 3: Implement the shared key, predicate, and upload guard**

Implement the exact interfaces above. `artifact_exists` lists with the exact key as prefix and then requires `obj.key == expected` and `obj.type != "Symlink"`. Keep the bucket optional for fake-based tests. Detect `auto` using the same machine and `/etc/os-release` rules as `reconcile.py`. Delegate `reconcile.object_key` to `checker.object_key` without changing its public result. Make `upload_list` collect uploaded keys and raise on an empty result.

- [ ] **Step 4: Run tests to verify GREEN**

Run the full command from Step 2. Expected: all Python tests pass, including existing upload tests updated for the explicit no-artifact error.

- [ ] **Step 5: Review the checkpoint**

Run: `git diff --check && git diff -- scripts/checker.py scripts/storage.py scripts/reconcile.py tests/test_checker.py tests/test_storage.py`
Expected: only the predicate, shared layout, upload guard, and related tests changed. Do not commit without confirmation.

### Task 2: Request-tag creation and deletion APIs

**Files:**
- Modify: `scripts/reconcile.py`
- Test: `tests/test_reconcile.py`

**Interfaces:**
- Consumes: nothing beyond current GitHub helpers.
- Produces: `request_build(stack, version, sha=None, session=None) -> str | None`; creates `refs/tags/<stack>@<version>` and returns the ref, or `None` for duplicate/no token.
- Produces: `delete_build_tag(stack, version, session=None) -> bool`; `True` for deleted/already absent, `False` only when no token is configured.
- Produces CLI: `reconcile.py request --stack S --version V [--sha SHA]` and `reconcile.py abandon --stack S --version V`.
- Changes: `cmd_success` only calls `resolve_failures`; it never creates a ref.

- [ ] **Step 1: Write failing tests**

Cover request creation at the requested SHA, duplicate 422 as skip, deletion success, deletion 404 as success, no-token behavior, and `cmd_success` resolving without any ref POST. Extend the fake session with `delete`. Assert all GitHub methods receive `timeout=30`.

```python
self.assertTrue(reconcile.delete_build_tag("nginx", "1.31.8", session=session))
self.assertEqual(success_rc, 0)
self.assertEqual([r for r in session.requests if r[1].endswith("/git/refs")], [])
```

- [ ] **Step 2: Run focused tests to verify RED**

Run: `PYTHONPATH=tests .venv/bin/python -m unittest -v test_reconcile.RequestBuildTest test_reconcile.SuccessReportTest`
Expected: new APIs/behavior are absent.

- [ ] **Step 3: Implement request/abandon and simplify success**

Reuse `_github_headers` and the current duplicate handling. Delete with `DELETE /repos/drycc/stacks/git/refs/tags/<stack>@<version>`, accepting 404. Add CLI parsers and error-to-nonzero mappings. Replace success-side `record_build` with request-side `request_build`. Apply the bounded timeout to existing GitHub get/post/patch/delete helpers used by alert/resolve too.

- [ ] **Step 4: Run focused and full tests to verify GREEN**

Run Step 2, then `.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q`. Expected: all pass.

- [ ] **Step 5: Review the checkpoint**

Run: `git diff --check && git diff -- scripts/reconcile.py tests/test_reconcile.py`
Expected: no success-side ref creation remains. Do not commit without confirmation.

### Task 3: Replace cron's direct build loop with tag scheduling

**Files:**
- Modify: `build.sh` (`reconcile` and request helper)
- Test: `tests/test_build.sh`

**Interfaces:**
- Consumes: Task 2 `reconcile.py request`.
- Produces: `reconcile-request STACK VERSION`; returns the underlying request command status and forwards `CI_COMMIT_SHA`.
- Changes: cron performs no per-item `build.sh all`, build upload, alert, or success reporting; it only schedules refs, then runs cleanup.

- [ ] **Step 1: Add failing shell regressions**

Extend the fake podman to record `reconcile.py request` and support a request failure. Test that a three-item plan creates three requests with SHA, invokes no stack build/upload, and still calls retention/cleaner once. A failed request must make the final reconcile non-zero while later requests and cleanup still run. Dry-run creates no request.

```bash
[ "$(count_calls "${RESULT_ROOT}/state/builds" "")" -eq 0 ]
grep -q -- "--sha 1111111111111111111111111111111111111111" "${RESULT_ROOT}/state/requests"
```

- [ ] **Step 2: Run shell tests to verify RED**

Run: `bash tests/test_build.sh`
Expected: current direct-build loop violates the no-build assertions.

- [ ] **Step 3: Implement request-only reconcile**

Replace the per-item build loop with `reconcile-request` calls. Track requested and failed counts, continue after individual failures, preserve final non-zero status and existing cleanup order. Keep `RECONCILE_DRY_RUN` read-only. Do not alter `build`, `upload`, `all`, or `reconcile-clean` algorithms in this task.

- [ ] **Step 4: Run shell and Python tests to verify GREEN**

Run: `bash tests/test_build.sh && .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q`
Expected: all pass.

- [ ] **Step 5: Review the checkpoint**

Run: `git diff --check && git diff -- build.sh tests/test_build.sh`
Expected: cron contains no direct item-build loop. Do not commit without confirmation.

### Task 4: Tag publish workflow and failure lifecycle

**Files:**
- Create: `.woodpecker/publish.yml`
- Modify: `build.sh`
- Test: `tests/test_build.sh`

**Interfaces:**
- Consumes: Task 1 artifact CLI/predicate; Task 2 abandon and success commands; existing `all`, `reconcile-report`, and log excerpt support.
- Produces: `./build.sh publish [STACK@VERSION]`; defaults to `CI_COMMIT_TAG`, validates the name and stack directory, and executes the exact lifecycle below.

- [ ] **Step 1: Add failing publish regressions**

Using fake podman, cover: existing object skips `all` and resolves; missing object builds and verifies; post-upload missing/error is failure; alert failure still calls abandon; resolve failure retains tag and returns success; malformed/removed-stack tags do not build; second deletion 404 is accepted. Assert real build failures return their original non-zero code and logs are passed to alert.

- [ ] **Step 2: Run tests to verify RED**

Run: `bash tests/test_build.sh`
Expected: `publish` is undefined.

- [ ] **Step 3: Implement publish and workflow YAML**

Implement a `run_logged LOG_FILE COMMAND...` helper that appends output with `tee -a` and returns the command's `PIPESTATUS[0]`. Preflight the artifact; skip only on exit 0. On missing (1), run `all`, then verify again. Any build/upload/verification failure performs best-effort alert followed by independent abandon and returns the original status. Existing/verified success calls success only for issue resolution, never request/record. Add `.woodpecker/publish.yml` with `when.event: tag`, both platform matrix values, exec labels, required secrets, and `./build.sh publish "${CI_COMMIT_TAG}"`.

- [ ] **Step 4: Run full tests to verify GREEN**

Run: `bash tests/test_build.sh && .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q && bash -n build.sh`
Expected: all pass.

- [ ] **Step 5: Review the checkpoint**

Run: `git diff --check && git diff -- build.sh .woodpecker/publish.yml tests/test_build.sh`
Expected: failure reporting cannot prevent abandon; success cannot recreate a tag. Do not commit without confirmation.

### Task 5: Idempotent obsolete-stack tag cleanup

**Files:**
- Create: `scripts/cleanup_obsolete_tags.py`
- Modify: `build.sh` (`reconcile-clean` only)
- Test: `tests/test_cleanup_obsolete_tags.py`
- Test: `tests/test_build.sh`

**Interfaces:**
- Produces: `obsolete_tag_refs(refs, current_stacks) -> list[str]`, accepting full `refs/tags/...` values and selecting only absent-stack `<stack>@<version>` tags.
- Produces CLI: `cleanup_obsolete_tags.py [--confirm] [--audit PATH]`; default dry-run, optional JSON audit output, non-zero on unexpected errors.

- [ ] **Step 1: Write failing tests**

Test pagination, malformed/unrelated ref rejection, exact absent-stack filtering, existing-stack protection with zero OSS, default dry-run with no DELETE, confirm deletion, 404 idempotence, partial failure, JSON audit contents, and final absence verification. Add a Shell assertion that `reconcile-clean` invokes the utility only after the OSS cleaner and honors both dry-run flags.

- [ ] **Step 2: Run tests to verify RED**

Run: `PYTHONPATH=tests .venv/bin/python -m unittest -v test_cleanup_obsolete_tags && bash tests/test_build.sh`
Expected: utility and wiring are absent.

- [ ] **Step 3: Implement the utility and cleanup hook**

Use GitHub `/git/refs/tags` pagination and `/git/{ref}` deletion with 30-second timeouts. Default to report-only plus audit JSON; require `--confirm` and a token for mutation. Accept 404 and verify the selected refs are absent afterward. Invoke the utility after OSS cleaning, with `--confirm` only when neither dry-run flag is set; propagate failure to `reconcile-clean` without changing `scripts/cleaner.py`.

- [ ] **Step 4: Run full tests to verify GREEN**

Run Step 2 and then `.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q`. Expected: all pass.

- [ ] **Step 5: Review the checkpoint**

Run: `git diff --check && git diff -- scripts/cleanup_obsolete_tags.py build.sh tests/test_cleanup_obsolete_tags.py tests/test_build.sh`
Expected: no existing-stack tag can be selected. Do not commit without confirmation.

### Task 6: Daily failure-issue reconciliation and cancellation

**Files:**
- Modify: `scripts/reconcile.py`
- Modify: `build.sh` (`reconcile-clean` only)
- Test: `tests/test_reconcile.py`
- Test: `tests/test_build.sh`

**Interfaces:**
- Consumes: Task 1 `storage.artifact_exists`; Task 2 timeout-enabled GitHub helpers.
- Produces: `reconcile_issues(arch=None, dry_run=False, session=None, bucket=None, stacks_dir=None) -> dict` with closed/cancelled/skipped counts.
- Produces CLI: `reconcile.py reconcile-issues [--arch ARCH|auto] [--dry-run]`.

- [ ] **Step 1: Write failing tests**

Cover paginated open-issue discovery and PR/title filtering; exact normal artifact closes as completed; missing artifact stays open; OSS error stays open and returns non-zero; removed stack closes every matching open issue as `not_planned` with a distinct comment, even with no tag/OSS; closed history is untouched; arch filtering prevents matrix overlap; dry-run sends no comment/PATCH. Verify a previous success-side resolution failure is repaired by this daily pass.

- [ ] **Step 2: Run tests to verify RED**

Run: `PYTHONPATH=tests .venv/bin/python -m unittest -v test_reconcile.ReconcileIssuesTest && bash tests/test_build.sh`
Expected: the operation is absent.

- [ ] **Step 3: Implement reconciliation and cron wiring**

List open issues with pagination and parse exact managed titles. For each issue in the selected arch, first cancel absent stacks as `not_planned`; otherwise close only when `artifact_exists` is true. Leave missing/error cases open and propagate errors for a later retry. Use a shared close helper for comment plus state/state_reason, keeping normal resolution and removal comments distinct. Invoke after obsolete-tag cleanup, forwarding auto arch and dry-run state, and propagate failure to `reconcile-clean`.

- [ ] **Step 4: Run full tests to verify GREEN**

Run: `bash tests/test_build.sh && .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q`
Expected: all pass.

- [ ] **Step 5: Review the checkpoint**

Run: `git diff --check && git diff -- scripts/reconcile.py build.sh tests/test_reconcile.py tests/test_build.sh`
Expected: no issue closes on missing/symlink/error; removed-stack closure says cancellation, not success. Do not commit without confirmation.

### Task 7: Documentation and whole-change verification

**Files:**
- Modify: `README.md`
- Review: all changed files

**Interfaces:**
- Consumes: all previous interfaces.

- [ ] **Step 1: Document operator workflows**

Document manual tag creation, existing-OSS skip, success retention, failure deletion/retry, rebuild after deleting OSS under an existing tag, stale-tag recovery after cancellation, daily obsolete-tag cleanup, daily issue reconciliation/cancellation, and both dry-run flags.

- [ ] **Step 2: Run final full verification**

Run:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
for test_script in tests/test_*.sh; do bash "$test_script" || exit 1; done
bash -n build.sh tests/test_build.sh
.venv/bin/python -m py_compile scripts/checker.py scripts/reconcile.py scripts/storage.py scripts/cleanup_obsolete_tags.py
git diff --check
```

Expected: every test passes and diff check is clean.

- [ ] **Step 3: Perform final lifecycle review**

Verify against the spec, line by line: single tag format, OSS normal-object invariant, no direct cron build, success without ref creation, failure deletion despite alert errors, daily resolution retry, removed-stack cancellation, existing-stack protection, and dry-run read-only behavior. Report any accepted limitations exactly; do not claim cancellation/deletion-failure recovery is automatic.

- [ ] **Step 4: Request integration instructions**

Present the diff and verification evidence to the user. Ask separately before any commit, push, dry-run pipeline change, or live tag/OSS/GitHub mutation.
