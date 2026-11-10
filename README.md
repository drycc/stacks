# stacks

A project for compiling binary packages, which is mainly provided for `install-stack`.

## Requesting a stack build with a tag

A Git tag named `<stack>@<version>` (for example `go@1.25.5`) is a build request:

- `<stack>` must be the name of a directory under `stacks/` in the revision the
  tag points to, matching `[a-z0-9][a-z0-9_-]*`.
- `<version>` is any non-empty string without `@`, `/` or whitespace.
- Push the tag and Woodpecker's tag workflow (`.woodpecker/publish.yml`) runs
  `./build.sh publish "${CI_COMMIT_TAG}"` on both `linux/amd64` and
  `linux/arm64`. One tag always drives both architectures; each matrix leg
  builds only its own arch/flavour.
- The same flow can be run locally as `./build.sh publish <stack>@<version>`
  (inside CI the tag defaults to `CI_COMMIT_TAG`).

Malformed tag names and tags for stacks without a directory in the checked-out
revision are rejected before anything is built.

## What the tag workflow does

For each architecture the pipeline evaluates one completion predicate: the
exact OSS key
`stacks/<stack>/<stack>-<version>-linux-<arch>-<flavour>.tar.gz` must exist
as a **normal, non-symlink object**. A symlink or a different key never counts
as built.

1. **Object already exists** (skip): build/upload is skipped, any open failure
   issue for this item is resolved, and the tag is kept.
2. **Object missing or symlink-only**: the item is built and uploaded through
   the normal `build.sh all` path, then the same predicate is checked again.
   Only a verified normal object counts as success, so a zero-artifact or
   symlink-only upload is a failure.
3. **Success retains the tag.** A successful build never creates or deletes
   any Git ref, so success never triggers another tag event.
4. **Failure deletes the tag** so a later cron can retry (see below).

Because each leg owns its own arch, one architecture can succeed and keep its
OSS object while the other fails and deletes the shared tag; a later cron then
recreates the tag only for the missing object.

### When a build fails

On any build/upload/verification failure of one matrix leg:

- A best-effort GitHub issue is created or commented on, deduplicated by the
  exact title `build failed for <stack>@<version> on <arch>/<flavour>`.
  Repeat failures append comments to the same issue, and amd64/arm64 keep
  independent issues. The issue includes the pipeline URL, commit SHA and a
  bounded build-log excerpt.
- The request tag `refs/tags/<stack>@<version>` is **always deleted**
  afterwards, independently of whether issue reporting succeeded. If both
  legs failed, the first deletion wins and the other's 404 is accepted as
  already deleted.
- The pipeline returns the original non-zero build status.
- With the tag gone and the object missing, the next nightly cron recreates
  the tag and the build is retried automatically.

### When only the issue resolution fails

If the artifact was built and verified but closing the failure issue failed,
the tag is retained and nothing is deleted. The daily `reconcile-issues` pass
closes the issue on a later day — but only after confirming that the exact
normal artifact exists in OSS.

## Nightly cron: request scheduling and daily cleanup

`.woodpecker/build.yml` runs `./build.sh reconcile` for cron events on both
platforms. Cron never builds stacks directly; it:

1. Plans missing versions from OSS per arch/flavour (unchanged planner,
   retention window and per-run caps).
2. Creates `refs/tags/<stack>@<version>` at `CI_COMMIT_SHA` for every planned
   item. A tag that already exists is reported and skipped — Git ref
   uniqueness is the deduplication between cron and manual requests. Creating
   the tag triggers the same tag workflow documented above.
3. Runs the daily cleanup phase in order: retention-list generation, OSS
   object cleanup (`scripts/cleaner.py`, unchanged policy), obsolete-tag
   cleanup, and failure-issue reconciliation.
4. Fails visibly if any request creation or cleanup step fails, while other
   items and cleanup steps still run.

## Daily obsolete-tag cleanup

`scripts/cleanup_obsolete_tags.py` runs nightly after OSS cleanup:

- Selects only `refs/tags/<stack>@<version>` refs whose stack directory no
  longer exists in the repository checkout. Malformed and unrelated refs are
  ignored.
- **Never deletes tags of stacks that still exist**, regardless of their OSS
  state.
- Default (dry-run): prints the selected refs and deletes nothing;
  `--audit PATH` additionally writes a JSON list with one entry per ref.
- `--confirm` (requires `GITHUB_TOKEN`): deletes the selected refs, accepts an
  already-absent ref (404) as success, and re-lists tags afterwards to verify
  every selected ref is gone. Unexpected list/delete/verification errors exit
  non-zero so the next daily run retries; partial progress is auditable and
  reruns are safe.

## Daily failure-issue reconciliation

`reconcile.py reconcile-issues` runs nightly after obsolete-tag cleanup and
processes the current arch only (so the amd64 and arm64 matrix legs never
touch each other's issues):

- Lists every **open** issue whose title is exactly
  `build failed for <stack>@<version> on <arch>/<flavour>`. Pull requests,
  human-written issues and other titles are never touched, and closed or
  historical issues are never revisited. No issue is ever deleted.
- **Stack directory removed**: the issue is closed as *not planned*
  (`state_reason=not_planned`) with a comment explaining the stack was
  removed and can never be built again. This is a cancellation, not a claim
  of build success, and works even with no OSS credentials or tag.
- **Stack still exists**: the issue is closed as *completed* only when the
  exact normal artifact exists for the issue's arch/flavour — this also
  repairs a success whose issue resolution failed earlier.
- **Artifact missing, or GitHub/OSS state cannot be determined**: the issue
  stays open for the normal tag retry path, and the run exits non-zero so the
  next daily run retries. Issues are never closed on uncertainty.

## Dry-run flags

- `RECONCILE_DRY_RUN=1`: `./build.sh reconcile` prints the plan but creates
  and deletes no request tags.
- `RECONCILE_DRY_RUN=1` or `CLEANER_DRY_RUN=1`: the whole cleanup phase runs
  in observation mode — the OSS cleaner, the obsolete-tag cleanup, and issue
  reconciliation print what they would do but perform no OSS deletion, no ref
  deletion, and no comment or issue-state change.

The production cron sets both flags to `0`. Preview a nightly run with:

```bash
RECONCILE_DRY_RUN=1 ./build.sh reconcile
python3 scripts/cleanup_obsolete_tags.py --audit obsolete-tags.json
.venv/bin/python scripts/reconcile.py reconcile-issues --arch auto --dry-run
```

## Manual recovery cases

Two situations have **no automatic recovery**; an operator must act:

1. **Stale request tag after a cancelled pipeline or failed tag deletion.**
   If a tag pipeline is cancelled or killed, or the failure-path tag deletion
   itself fails, the tag can remain while the artifact is missing. Cron then
   skips the item indefinitely (the tag already exists). Delete the
   `refs/tags/<stack>@<version>` ref manually; the next cron recreates it and
   retries.
2. **Rebuilding after deleting OSS under a retained success tag.** The
   existing tag makes cron skip the request, and the tag workflow skips the
   build only while the object exists. To rebuild: rerun the old tag pipeline
   after deleting the object, or delete and recreate the tag manually.

Related limitation: the daily cleanup never deletes tags of stacks that still
exist, even when all their OSS objects are gone. Rebuild those versions
through the tag workflow (or delete/recreate the tag) instead.

## Development

Run the test suites with `./build.sh test` (requires podman), or directly:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
for test_script in tests/test_*.sh; do bash "$test_script"; done
```
