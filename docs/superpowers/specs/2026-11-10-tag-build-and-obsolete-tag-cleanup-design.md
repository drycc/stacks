# Tag-driven builds and obsolete-tag cleanup

Date: 2026-11-10
Status: Design for review

## Background

The current nightly flow plans missing stack versions from OSS, builds and uploads them in the cron workflow, and creates a `<stack>@<version>` tag after success. Tags currently record successful builds but trigger no workflow. This makes it impossible to request an individual version through the same path without running the whole reconcile flow.

The current OSS cleaner only deletes OSS objects. It has no GitHub tag cleanup logic. A separate requirement is to remove tags whose stack directory no longer exists in the repository.

## Goals

1. Allow a user to build one specific version by creating a `<stack>@<version>` tag.
2. Use the same tag-driven build path for manual requests and nightly reconcile.
3. Keep OSS as the only build-completion standard:
   - the exact key must exist and be a normal, non-symlink OSS object;
   - skip a tag build only when that predicate is already true;
   - verify the same predicate again after upload before resolving an issue.
4. Avoid duplicate work when cron and a manual request refer to the same tag:
   - an existing tag is treated as an existing build request and is not recreated;
   - Git ref uniqueness is the deduplication mechanism, with idempotent handling for at-least-once delivery.
5. Preserve a successful tag. Delete a tag after a failed build so a later cron can recreate it and retry automatically.
6. Run a simple idempotent cleanup every day that deletes tags belonging only to stacks absent from the current repository.
7. Reconcile open failure issues every day: close them when their exact normal artifact exists, cancel them when their stack no longer exists, and otherwise leave them open for retry.
8. Keep the implementation small. Do not add Woodpecker status APIs, architecture-specific request-tag namespaces, distributed locks, or GitHub logic to `scripts/cleaner.py`.

## Non-goals and accepted limitations

- No automatic recovery when a pipeline is cancelled/killed or when the failure-path tag deletion itself fails. In these cases the leftover tag causes cron to skip; an operator deletes it to allow another attempt.
- A successful tag left in place after its OSS object is manually deleted will make cron skip recreation. To rebuild, rerun the old tag pipeline after deleting the object, or delete and recreate the tag manually.
- The daily cleanup does not delete tags for versions of stacks that still exist, even when all OSS objects for that version are absent.
- Daily issue reconciliation does not permanently delete issues. It closes open managed failure issues when their artifact exists and cancels them when their stack is removed; closed/historical issues are left untouched.
- Concurrent builds that independently target the same exact OSS key are not prevented by a distributed lock. The normal tag-unique path prevents this; uploading the same key remains idempotent as a final safeguard.
- `scripts/cleaner.py` and its OSS retention policy are unchanged.

## Current state

- `.woodpecker/build.yml` runs `./build.sh reconcile` only for cron, on amd64 and arm64.
- `.woodpecker/test.yml` runs tests for push events and is unrelated to build triggering.
- `build.sh reconcile` plans from OSS, builds each item, uploads, reports failures, and creates a success tag.
- `scripts/reconcile.py` creates success tags and creates/closes failure issues.
- `scripts/cleaner.py` only deletes OSS objects selected by retention.
- The repository has no tag-triggered build workflow at present.

## Design

### 1. One tag meaning

A `<stack>@<version>` tag is both a build request and, after success, the build record.

Its lifecycle is:

```text
created manually or by cron
        │
        ▼
tag workflow checks for the exact normal OSS object for the current arch/flavour
        │
        ├─ predicate true → skip build, keep the tag, and resolve the issue
        │
        └─ predicate false → build and upload
                      │
                      ▼
                verify the predicate again
                      │
                      ├─ verified → keep the tag and resolve the issue
                      │
                      └─ build/upload/verification failed
                          ├─ create/append the failure issue (best effort)
                          ├─ always attempt to delete the tag
                          └─ return the original non-zero status
```

The next cron sees a missing OSS object. If the tag is absent it creates the tag; if the tag exists it skips. Therefore deleting a failed tag enables an automatic retry on a later cron run.

A success-side issue resolution failure is not a build failure and must never trigger tag deletion. The tag is retained and the daily issue reconciliation retries closure after confirming the artifact. A genuine build/upload/verification failure always attempts tag deletion even when alert creation/commenting also fails; the two errors are logged independently and the original non-zero build status is preserved.

### 2. Nightly reconcile becomes request scheduling

The existing OSS planner remains unchanged. It still determines missing versions independently for amd64/arm64 and respects current retention and per-run limits.

The per-item build loop is replaced by request scheduling:

```text
for each planned <stack>@<version>:
    if the Git ref refs/tags/<stack>@<version> exists:
        skip
    else:
        create it at CI_COMMIT_SHA
```

Both matrix legs may attempt to create the same ref. GitHub permits only one creation; the other receives the already-exists result and skips. The successful creation produces one tag event, which starts the normal matrix tag workflow.

Cron no longer runs stack builds. It continues to:

- print scheduling and duplicate-skip results;
- run retention generation and OSS cleanup;
- run the obsolete-stack tag cleanup after OSS cleanup;
- fail visibly if request creation or cleanup fails.

`RECONCILE_DRY_RUN=1` prints the plan but creates/deletes no refs and performs no real cleanup.

### 3. Tag workflow

Add `.woodpecker/publish.yml` with:

- `when.event: tag`;
- the existing amd64/arm64 matrix and exec labels;
- the same build/OSS/GitHub secrets required by the current cron workflow.

The workflow parses `CI_COMMIT_TAG` as `<stack>@<version>` and rejects malformed names or stacks without a directory in the checked-out revision. Rejecting unknown stacks also prevents daily obsolete-tag cleanup from racing a valid new build for a removed stack.

For each matrix leg:

1. Derive arch and flavour inside the buildpack image, matching current build behavior.
2. Check the exact OSS key and object type:
   `stacks/<stack>/<stack>-<version>-linux-<arch>-<flavour>.tar.gz` must exist and be a normal, non-symlink object.
3. If the predicate is true, skip build/upload, resolve the corresponding failure issue, and keep the tag. A resolution error is logged for daily retry and does not delete the tag.
4. If it is absent or only a symlink exists, run the existing build/upload path while preserving live logs and capturing a bounded excerpt for reporting.
5. After upload, require the expected key to exist as a normal object. A zero-artifact/no-op upload, a symlink-only key, or a verification error is not success.
6. Only after that verification, resolve the corresponding failure issue and keep the tag.
7. On any build/upload/verification failure, create/append the failure issue with the log excerpt on a best-effort basis, always attempt to delete the tag independently of alert success, and return the original non-zero build status.

A successful tag workflow must not create another tag. The request tag already exists, so success only resolves the issue and retains the ref. This avoids a second tag event when one architecture fails and deletes the ref while the other architecture succeeds later.

Both matrix legs may attempt to delete the same tag after failures. The first deletion succeeds; a subsequent 404/already-absent result is accepted as already deleted.

### 4. Artifact completion invariant

Use one shared predicate everywhere completion is evaluated:

> The exact expected key exists and its OSS object type is normal, not `Symlink`.

The storage operation must:

- accept stack, version, arch, and flavour explicitly;
- construct the exact expected key without fuzzy prefix matching;
- inspect the object type, not merely treat any HEAD/200 response as completion;
- distinguish `exists`, `missing`, and `error`;
- never create, modify, or delete an object.

Use the predicate before building, after upload, and during daily issue reconciliation. The upload path must also prove that it uploaded at least one expected artifact; the current `upload_list` behavior of matching no files and returning successfully is not acceptable for this flow. Missing, symlink-only, zero-artifact, and verification-error outcomes must never close an issue as successfully built. Tag presence alone never proves an artifact exists.

### 5. Reconcile/reporting API changes

Adjust `scripts/reconcile.py` responsibilities rather than adding another orchestration layer:

- request scheduling creates `<stack>@<version>` refs and treats already-exists as a skip;
- successful publishing only resolves failure issues and does not create refs;
- success-side resolution errors leave the ref intact and are retried by daily issue reconciliation;
- failed publishing attempts request-ref deletion independently of alert success, accepting already-absent as success and preserving the original build failure;
- existing failure issue creation, repeat comments, pipeline/commit metadata, and bounded logs are reused;
- managed issue wording must not claim every item stays on the nightly plan forever: manual requests, removed stacks, and retention boundaries are exceptions;
- GitHub operations receive bounded timeouts so a stalled API call cannot hang the workflow indefinitely.

`build.sh` retains the existing internal build/upload command for the tag workflow. The cron build loop is removed in favor of ref creation. Shared log capture/reporting behavior is factored only as needed to avoid duplicating the existing implementation.

### 6. Daily obsolete-stack tag cleanup

Add `scripts/cleanup_obsolete_tags.py` as an independently testable, idempotent utility.

Inputs and discovery:

1. Read stack directory names from the checked-out repository.
2. List all GitHub tag refs with pagination.
3. Parse only `<stack>@<version>` names.
4. Select refs whose stack is absent from the current directories.
5. Ignore malformed/unrelated refs and every ref belonging to an existing stack, regardless of OSS state.

Modes:

- Default: dry-run. Print every selected ref and write a JSON audit list; delete nothing.
- `--confirm`: delete selected remote refs through GitHub, accepting already-absent as success, then verify that every selected ref is absent.

Any unexpected list/delete/verification error returns non-zero. Successfully processed items are logged so a partial run can be audited and safely rerun.

Invoke it at the end of the existing cron cleanup with `GITHUB_TOKEN`. Use `--confirm` only when neither `RECONCILE_DRY_RUN` nor `CLEANER_DRY_RUN` is enabled; in either dry-run mode, invoke the utility in its default dry-run mode so it only reports candidates. A failure fails `reconcile-clean`, so the next daily run retries. The OSS cleaner itself remains unchanged.

Because the planner no longer includes removed stacks, new legitimate build requests for those stacks should not occur. The tag workflow's unknown-stack validation provides a second guard.

### 7. Daily failure-issue reconciliation

Add an idempotent `reconcile-issues` operation to `scripts/reconcile.py` and run it after OSS cleanup and obsolete-tag cleanup. This is the recovery mechanism for success-side resolution errors and for removed stacks; it is not based on whether a tag still exists.

For every open issue matching the managed title format `build failed for <stack>@<version> on <arch>/<flavour>`:

1. Parse the exact `(stack, version, arch, flavour)` key and ignore pull requests and unrelated issue titles.
2. If the stack directory is absent, close the issue with `state_reason=not_planned` and a distinct comment explaining that the stack was removed and no more builds are planned. This is cancellation, not a claim of build success, and applies across all versions/arches/flavours even when no artifact or tag exists.
3. Otherwise, evaluate the exact normal-artifact predicate for that arch/flavour. If true, close the issue as completed with the normal successful-build comment.
4. If the artifact is absent, leave the issue open for the normal tag retry path.
5. If OSS or GitHub state cannot be determined, leave the issue open and return non-zero so the next daily run retries. Never close on uncertainty.

List open issues with pagination, and make comment/close operations idempotent. Closed and historical issues are not modified, and no issue is permanently deleted. `RECONCILE_DRY_RUN` or `CLEANER_DRY_RUN` selects report-only behavior for this operation as well.

### 8. Expected behavior matrix

| Situation | Result |
|---|---|
| Manual tag, object absent | Build/upload, retain tag on success |
| Manual tag, object already present | Skip build, retain tag |
| Cron finds missing object and no tag | Create tag |
| Cron finds missing object and tag exists | Skip request creation |
| One arch exists, the other missing | Existing arch skips; missing arch builds |
| One arch succeeds, the other fails and deletes tag | Successful object remains; later cron recreates tag only if an object is missing |
| Build fails and tag deletion succeeds | Later cron recreates tag and retries |
| Alert creation/comment fails during a real build failure | Still attempt tag deletion; log alert and deletion errors independently |
| Artifact exists but success-side issue resolution fails | Retain tag; daily issue reconciliation verifies the artifact and retries closure |
| Upload returns success without the expected normal artifact, or key is symlink-only | Treat as unsuccessful; do not resolve the issue |
| Pipeline cancelled or tag deletion fails | Tag may remain; cron skips until operator deletes it |
| OSS object deleted while success tag remains | Cron skips; rerun old tag pipeline or delete/recreate tag manually |
| Stack removed from repository | No new plan; daily cleanup deletes its leftover tags and cancels its open failure issues as `not_planned` |
| Existing stack with missing OSS | Daily cleanup never deletes its tag and leaves its failure issue open |
| Concurrent duplicate tag events or duplicate issues | Build/report operations are idempotent; every matching open issue is commented/closed, but strict atomic uniqueness is not claimed |

## Files expected to change

- `.woodpecker/build.yml`: cron request scheduling and cleanup wiring only.
- `.woodpecker/publish.yml`: new tag-triggered matrix build workflow.
- `build.sh`: replace cron's direct-build loop with tag requests; add tag-publish orchestration while reusing build/upload/reporting.
- `scripts/reconcile.py`: separate request-tag creation, success resolution, failure-tag deletion, and daily open-issue reconciliation responsibilities.
- `scripts/storage.py`: add read-only exact normal-object checks and make expected-artifact upload enforcement explicit.
- `scripts/cleanup_obsolete_tags.py`: new idempotent obsolete-stack tag cleanup.
- `tests/test_build.sh`: scheduling/publish behavior and exit/cleanup guarantees.
- `tests/test_reconcile.py`: request creation, duplicate skip, success without ref creation, failure deletion, and daily issue reconciliation/cancellation.
- `tests/test_storage.py`: normal/symlink/missing/error object states, expected-artifact upload enforcement, and post-upload verification.
- `tests/test_cleanup_obsolete_tags.py`: filtering, pagination, dry-run, confirm, 404s, partial failures, and verification.
- `README.md`: manual tag build, rebuild, failure retry, and cleanup usage.

`scripts/cleaner.py` is intentionally not modified.

## Test strategy

### Unit and shell tests

- Existing stack directory and discovery tables remain consistent.
- OSS existence uses the exact key and propagates service errors.
- Existing exact normal OSS objects skip build/upload and retain the tag.
- Symlink-only keys and no-op uploads do not satisfy completion.
- Missing objects build/upload and retain the tag only after post-upload verification succeeds.
- Post-upload verification errors are treated as unsuccessful and cannot close an issue.
- Success never creates another ref or triggers another tag event.
- Failure creates/appends a rich issue, deletes the ref once, accepts a second 404, and preserves the original build failure.
- Alert failure still permits failure-tag deletion; success-side resolution failure retains the tag.
- Daily issue reconciliation closes issues only for exact normal artifacts, retries earlier resolution failures, cancels removed-stack issues as `not_planned`, and leaves missing/error cases open.
- Cron duplicate ref creation produces no second direct stack build; any duplicate events are handled idempotently.
- Dry-run performs no OSS, GitHub ref, issue-comment, or issue-state mutation.
- Obsolete cleanup includes only absent stacks, paginates correctly, is idempotent, and verifies deletion.
- Existing stacks are protected even with zero OSS objects.
- Reporting failures and ref deletion failures are logged distinctly and do not get mistaken for build failures; GitHub calls have bounded timeouts.
- Full Python and Shell suites run after implementation.

### Staged verification

1. Run all tests locally.
2. Run cron in dry-run mode and verify no refs or OSS objects change.
3. Use one inexpensive test stack/version to verify manual tag creation, OSS skip, success retention, and failure retry.
4. Run the obsolete cleanup in dry-run mode and review its JSON list before enabling `--confirm` in cron.

## Rollout

1. Finish any active old-style cron build before enabling the new flow.
2. Deploy the tag workflow and the cron scheduling change together so new request tags always have a consumer.
3. Existing tags do not generate events retroactively and need no migration.
4. Keep dry-run enabled for the first scheduled planning/cleanup review, then enable real requests.
5. Document the two accepted manual recovery cases: cancelled/deletion-failed stale tags and rebuilding after deleting OSS under an existing success tag.

## Success criteria

- A user can request one version with only a `<stack>@<version>` tag.
- Nightly and manual requests use the same build/upload path.
- Existing exact normal OSS objects are not rebuilt, and no issue is closed as successful without that predicate being verified.
- Duplicate tag creation is skipped without a duplicate direct cron build; any duplicate delivery is handled idempotently.
- Successful tags remain; failed tags are deleted and recreated by a later cron.
- Alert failures do not prevent failure-tag deletion, while success-side resolution failures never delete tags and are retried by daily issue reconciliation.
- Removed stacks' leftover tags are deleted daily, and their open failure issues are cancelled without claiming build success or deleting issue history.
- Existing stacks' tags are never deleted by obsolete-stack cleanup, and issues with missing/uncertain artifacts remain open.
- The implementation adds no Woodpecker API orchestration and leaves OSS retention cleaner logic unchanged.
