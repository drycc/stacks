#!/bin/bash
set -e
set -u
# Build a base image
DRYCC_REGISTRY=${DRYCC_REGISTRY:-${DEV_REGISTRY:-registry.drycc.cc}}

# make sure we are in this dir
# (BASH_SOURCE works both when executed and when sourced by the tests)
CURRENT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")"; pwd)
#dist dir
DIST_DIR="${CURRENT_DIR}"/_dist

# codename
CODENAME="${CODENAME:?codename is required}"
# buildpack-dep image name
BUILDPACK_DEP_IMAGE="${DRYCC_REGISTRY}"/drycc/buildpack-dep:"${CODENAME}"

function create-buildpack-dep {
  if [ "${SKIP_CREATE_BUILDPACK_DEP:-}" = "1" ]; then
    # the image was already created by this run (see reconcile)
    return 0
  fi
  # build buildpack-dep image
  podman build --pull -f "${CURRENT_DIR}"/Dockerfile --build-arg CODENAME="${CODENAME}" --build-arg DRYCC_REGISTRY="${DRYCC_REGISTRY}" . -t "${BUILDPACK_DEP_IMAGE}"
}

function test {
  # Run the complete suite in the same dependency environment used by the
  # nightly reconcile, cleaner, and retention generator.
  create-buildpack-dep
  podman run --rm \
    -v "${CURRENT_DIR}":"${CURRENT_DIR}" \
    -w "${CURRENT_DIR}" \
    "${BUILDPACK_DEP_IMAGE}" \
    bash -c '
      python -m unittest discover -s tests -p "test_*.py" -v &&
      for test_script in tests/test_*.sh; do bash "$test_script" || exit 1; done
    '
}

function build {
  mkdir -p "$DIST_DIR"
  STACK_NAME="${1:?STACK_NAME is required}"
  stack_version="${2:?stack_version is required}"
  create-buildpack-dep
  podman run --rm \
    --privileged=true \
    --env STACK_DOWNLOAD_URL="${STACK_DOWNLOAD_URL:-}" \
    --env STACK_NAME="${STACK_NAME}" \
    --env STACK_VERSION="${stack_version}" \
    -v "${DIST_DIR}":"${DIST_DIR}" \
    -v "${CURRENT_DIR}/stacks/${STACK_NAME}":/workspace \
    -v "${CURRENT_DIR}/scripts/stack-utils":/usr/bin/stack-utils \
    -w /workspace \
    "${BUILDPACK_DEP_IMAGE}" \
    ./build.sh "${DIST_DIR}"
}

function upload {
  STACK_NAME="${1:?stack_name is required}"
  create-buildpack-dep
  podman run --rm \
    --env OSS_ENDPOINT=${OSS_ENDPOINT} \
    --env OSS_ACCESS_KEY_ID=${OSS_ACCESS_KEY_ID} \
    --env OSS_ACCESS_KEY_SECRET=${OSS_ACCESS_KEY_SECRET} \
    -v "${DIST_DIR}":"${DIST_DIR}" \
    -v "${CURRENT_DIR}/stacks:/workspace" \
    -v "${CURRENT_DIR}/scripts:/scripts" \
    -w /workspace \
    "${BUILDPACK_DEP_IMAGE}" \
    python3 /scripts/storage.py upload "${STACK_NAME}" "${DIST_DIR}"
}

function symlink {
  podman run --rm \
    --env OSS_ENDPOINT=${OSS_ENDPOINT} \
    --env OSS_ACCESS_KEY_ID=${OSS_ACCESS_KEY_ID} \
    --env OSS_ACCESS_KEY_SECRET=${OSS_ACCESS_KEY_SECRET} \
    -v "${DIST_DIR}":"${DIST_DIR}" \
    -v "${CURRENT_DIR}/stacks:/workspace" \
    -v "${CURRENT_DIR}/scripts:/scripts" \
    -w /workspace \
    "${BUILDPACK_DEP_IMAGE}" \
    python3 /scripts/storage.py symlink "${1}" "${2}"
}


function run_logged() {
  local log_file="${1:?LOG_FILE is required}" command_status
  shift 1
  "$@" 2>&1 | tee -a "${log_file}"
  command_status=${PIPESTATUS[0]}
  return "${command_status}"
}


function reconcile-report() {
  # Report a per-item build result to GitHub: "alert" creates or comments on
  # the deduplicated issue for a failed build; "success" only closes the open
  # failure issue and retains the request tag. Reporting problems never change
  # the publish or reconcile exit status.
  local action="${1:?action is required}"
  local stack="${2:?stack is required}"
  local version="${3:?version is required}"
  local log_file="${4:-}"
  [ -n "${GITHUB_TOKEN:-}" ] || return 0
  local report_args=("${action}" --stack "${stack}" --version "${version}")
  if [ "${action}" = "alert" ]; then
    report_args+=(--pipeline-url "${CI_PIPELINE_URL:-}" --sha "${CI_COMMIT_SHA:-}")
    if [ -n "${log_file}" ]; then
      report_args+=(--log-file "${log_file}")
    fi
  fi
  if ! podman run --rm \
    --env GITHUB_TOKEN="${GITHUB_TOKEN}" \
    --env CI_COMMIT_SHA="${CI_COMMIT_SHA:-}" \
    -v "${CURRENT_DIR}":"${CURRENT_DIR}" \
    -w "${CURRENT_DIR}" \
    "${BUILDPACK_DEP_IMAGE}" \
    python3 scripts/reconcile.py "${report_args[@]}"; then
    echo "reconcile: ${action} reporting failed for ${stack}@${version}" >&2
  fi
}


function reconcile-request() {
  # Create the tag that schedules a stack build. Keep the request command as
  # the final command so its status is returned unchanged to the caller.
  local stack="${1:?stack is required}"
  local version="${2:?version is required}"
  local request_args=(request --stack "${stack}" --version "${version}")
  if [ -n "${CI_COMMIT_SHA:-}" ]; then
    request_args+=(--sha "${CI_COMMIT_SHA}")
  fi
  podman run --rm \
    --env GITHUB_TOKEN="${GITHUB_TOKEN:-}" \
    --env CI_COMMIT_SHA="${CI_COMMIT_SHA:-}" \
    -v "${CURRENT_DIR}":"${CURRENT_DIR}" \
    -w "${CURRENT_DIR}" \
    "${BUILDPACK_DEP_IMAGE}" \
    python3 scripts/reconcile.py "${request_args[@]}"
}


function reconcile-clean() {
  # Clean old OSS objects and reconcile open failure issues after all planned
  # builds have been attempted.
  # Each matrix leg removes only its own arch, so amd64/arm64 never overlap. Dry-run
  # mode is always non-destructive; the cron configuration opts into
  # real deletion with CLEANER_DRY_RUN=0.
  local clean_args=(-n "${CLEANER_KEEP_COUNT:-2}" --arch auto)
  local obsolete_tag_args=()
  local issue_args=(--arch auto)
  if [ "${RECONCILE_DRY_RUN:-}" = "1" ] || [ "${CLEANER_DRY_RUN:-}" = "1" ]; then
    clean_args+=(--dry-run)
    issue_args+=(--dry-run)
  else
    clean_args+=(--confirm)
    obsolete_tag_args+=(--confirm)
  fi
  local generated_retention="${DIST_DIR}/retention-list.generated.txt"
  mkdir -p "${DIST_DIR}"
  echo "reconcile: generating dynamic retention list"
  if ! podman run --rm \
    --env GITHUB_TOKEN="${GITHUB_TOKEN:-}" \
    -v "${CURRENT_DIR}":"${CURRENT_DIR}" \
    -w "${CURRENT_DIR}" \
    "${BUILDPACK_DEP_IMAGE}" \
    python3 scripts/retention.py \
    --repos retention-repo.txt \
    --static retention-list.txt \
    --output "${generated_retention}"; then
    echo "reconcile: retention generation failed" >&2
    return 1
  fi
  echo "reconcile: cleaning old OSS objects (keep=${CLEANER_KEEP_COUNT:-2} per series)"
  if ! podman run --rm \
    --env OSS_ENDPOINT="${OSS_ENDPOINT:-}" \
    --env OSS_ACCESS_KEY_ID="${OSS_ACCESS_KEY_ID:-}" \
    --env OSS_ACCESS_KEY_SECRET="${OSS_ACCESS_KEY_SECRET:-}" \
    -v "${CURRENT_DIR}":"${CURRENT_DIR}" \
    -w "${CURRENT_DIR}" \
    "${BUILDPACK_DEP_IMAGE}" \
    python3 scripts/cleaner.py oss-stacks "${clean_args[@]}" \
    --retention-list "${generated_retention}"; then
    echo "reconcile: cleanup failed" >&2
    return 1
  fi
  echo "reconcile: cleaning obsolete stack tags"
  if ! podman run --rm \
    --env GITHUB_TOKEN="${GITHUB_TOKEN:-}" \
    -v "${CURRENT_DIR}":"${CURRENT_DIR}" \
    -w "${CURRENT_DIR}" \
    "${BUILDPACK_DEP_IMAGE}" \
    python3 scripts/cleanup_obsolete_tags.py "${obsolete_tag_args[@]}"; then
    echo "reconcile: obsolete tag cleanup failed" >&2
    return 1
  fi
  echo "reconcile: reconciling open failure issues"
  if ! podman run --rm \
    --env GITHUB_TOKEN="${GITHUB_TOKEN:-}" \
    --env OSS_ENDPOINT="${OSS_ENDPOINT:-}" \
    --env OSS_ACCESS_KEY_ID="${OSS_ACCESS_KEY_ID:-}" \
    --env OSS_ACCESS_KEY_SECRET="${OSS_ACCESS_KEY_SECRET:-}" \
    -v "${CURRENT_DIR}":"${CURRENT_DIR}" \
    -w "${CURRENT_DIR}" \
    "${BUILDPACK_DEP_IMAGE}" \
    python3 scripts/reconcile.py reconcile-issues "${issue_args[@]}"; then
    echo "reconcile: issue reconciliation failed" >&2
    return 1
  fi
}


function reconcile {
  create-buildpack-dep
  # Plan inside the buildpack image so /etc/os-release matches the build
  # environment, the same source stack-utils uses for OS_FLAVOUR. All
  # arguments are forwarded to "reconcile.py plan"; arch and flavour are
  # detected inside the image unless given explicitly (--arch etc).
  local plan
  plan=$(podman run --rm \
    --env OSS_ENDPOINT="${OSS_ENDPOINT:-}" \
    --env OSS_ACCESS_KEY_ID="${OSS_ACCESS_KEY_ID:-}" \
    --env OSS_ACCESS_KEY_SECRET="${OSS_ACCESS_KEY_SECRET:-}" \
    --env GITHUB_TOKEN="${GITHUB_TOKEN:-}" \
    -v "${CURRENT_DIR}":"${CURRENT_DIR}" \
    -w "${CURRENT_DIR}" \
    "${BUILDPACK_DEP_IMAGE}" \
    python3 scripts/reconcile.py plan "$@")
  if [ -z "${plan}" ]; then
    echo "reconcile: nothing to build"
  fi
  if [ "${RECONCILE_DRY_RUN:-}" = "1" ]; then
    # Observation mode: print the plan the nightly cron would build so it
    # can be reviewed in the pipeline logs before enabling real builds.
    echo "reconcile: dry run, $(printf '%s\n' "${plan}" | grep -c .) item(s) to build:"
    printf '%s\n' "${plan}"
    reconcile-clean
    return $?
  fi
  local requested=0 failed=0
  local failed_items=()
  local item
  while read -r item; do
    [ -n "${item}" ] || continue
    echo "reconcile: requesting ${item}"
    if reconcile-request "${item%@*}" "${item#*@}"; then
      requested=$((requested + 1))
    else
      failed=$((failed + 1))
      failed_items+=("${item}")
      echo "reconcile: failed to request ${item}" >&2
    fi
  done <<< "${plan}"
  echo "reconcile: done, requested=${requested} failed=${failed}"
  echo "reconcile: failed (${failed}):"
  for item in "${failed_items[@]}"; do
    echo "  ${item}"
  done

  # Item failures must not prevent retention cleanup. Preserve their failed
  # status and report it after cleanup so the pipeline still fails visibly.
  local cleanup_status=ok
  if ! reconcile-clean; then
    cleanup_status=failed
  fi
  if [ "${failed}" -ne 0 ] || [ "${cleanup_status}" != "ok" ]; then
    echo "reconcile: run failed: ${failed} request failure(s), cleanup=${cleanup_status}" >&2
    return 1
  fi
  echo "reconcile: run succeeded"
}


function patch() {
    # Validate arguments
    if [[ $# -ne 3 ]]; then
        echo "Usage: ${FUNCNAME[0]} <tar.gz> <inner_file> <replacement>" >&2
        return 1
    fi
    local tar_file="$1"
    local inner_file="$2"
    local replacement_file="$3"
    # Check if files exist
    if [[ ! -f "$tar_file" ]]; then
        echo "Error: Tar file '$tar_file' not found" >&2
        return 1
    fi
    if [[ ! -f "$replacement_file" ]]; then
        echo "Error: Replacement file '$replacement_file' not found" >&2
        return 1
    fi
    # Create temporary directory
    local temp_dir
    temp_dir=$(mktemp -d) || {
        echo "Error: Failed to create temporary directory" >&2
        return 1
    }
    trap "rm -rf '$temp_dir'" EXIT
    # Extract tar file
    if ! tar -xzf "$tar_file" -C "$temp_dir" 2>/dev/null; then
        echo "Error: Failed to extract '$tar_file'" >&2
        return 1
    fi
    # Check if inner file exists in archive
    if [[ ! -f "${temp_dir}/${inner_file}" ]]; then
        echo "Error: File '$inner_file' not found in archive" >&2
        return 1
    fi
    # Replace the file
    if ! cp "$replacement_file" "${temp_dir}/${inner_file}"; then
        echo "Error: Failed to replace file" >&2
        return 1
    fi

    tar --numeric-owner -czf "${tar_file: :-7}.patched.tar.gz" -C "$temp_dir" . --transform='s,^./,,'
    echo "Success: File replaced in '$tar_file'"
    return 0
}

function all() {
  STACK_NAME=$(echo "${1}" | cut -d '@' -f 1)
  STACK_VERSION=$(echo "${1}" | cut -d '@' -f 2)

  build "${STACK_NAME}" "${STACK_VERSION}"
  upload "${STACK_NAME}"
}


function publish-artifact-exists() {
  local stack="$1" version="$2" log_file="$3"
  run_logged "${log_file}" podman run --rm \
    --env OSS_ENDPOINT="${OSS_ENDPOINT:-}" \
    --env OSS_ACCESS_KEY_ID="${OSS_ACCESS_KEY_ID:-}" \
    --env OSS_ACCESS_KEY_SECRET="${OSS_ACCESS_KEY_SECRET:-}" \
    -v "${CURRENT_DIR}":"${CURRENT_DIR}" \
    -w "${CURRENT_DIR}" \
    "${BUILDPACK_DEP_IMAGE}" \
    python3 scripts/storage.py artifact-exists "${stack}" "${version}" \
    --arch auto --flavour auto
}


function publish-failure() {
  # Reporting is best-effort. In particular, an alert failure must never skip
  # the independent request-tag deletion or replace the original build status.
  local stack="$1" version="$2" log_file="$3"
  reconcile-report alert "${stack}" "${version}" "${log_file}" || true
  if ! podman run --rm \
    --env GITHUB_TOKEN="${GITHUB_TOKEN:-}" \
    -v "${CURRENT_DIR}":"${CURRENT_DIR}" \
    -w "${CURRENT_DIR}" \
    "${BUILDPACK_DEP_IMAGE}" \
    python3 scripts/reconcile.py abandon --stack "${stack}" --version "${version}"; then
    echo "publish: abandon failed for ${stack}@${version}" >&2
  fi
  return 0
}


function publish() {
  if [ "$#" -gt 1 ]; then
    echo "Usage: ${FUNCNAME[0]} [STACK@VERSION]" >&2
    return 2
  fi
  local tag stack version log_file status
  if [ "$#" -eq 1 ]; then
    tag="$1"
  else
    tag="${CI_COMMIT_TAG:-}"
  fi
  if [[ ! "${tag}" =~ ^[a-z0-9][a-z0-9_-]*@[^@/[:space:]]+$ ]]; then
    echo "publish: invalid tag '${tag}', expected STACK@VERSION" >&2
    return 2
  fi
  stack="${tag%%@*}"
  version="${tag#*@}"
  if [ ! -d "${CURRENT_DIR}/stacks/${stack}" ]; then
    echo "publish: unknown stack '${stack}'" >&2
    return 2
  fi

  mkdir -p "${DIST_DIR}"
  log_file=$(mktemp "${DIST_DIR}/publish.XXXXXX.log")
  if run_logged "${log_file}" create-buildpack-dep; then
    status=0
  else
    status=$?
    publish-failure "${stack}" "${version}" "${log_file}"
    rm -f "${log_file}" || true
    return "${status}"
  fi

  if publish-artifact-exists "${stack}" "${version}" "${log_file}"; then
    echo "publish: exact artifact already exists for ${tag}; skipping build"
    reconcile-report success "${stack}" "${version}"
    rm -f "${log_file}" || true
    return 0
  else
    status=$?
  fi
  if [ "${status}" -ne 1 ]; then
    echo "publish: artifact preflight failed for ${tag} (status ${status})" >&2
    publish-failure "${stack}" "${version}" "${log_file}"
    rm -f "${log_file}" || true
    return "${status}"
  fi

  echo "publish: building ${tag}"
  if run_logged "${log_file}" env SKIP_CREATE_BUILDPACK_DEP=1 \
    bash "${CURRENT_DIR}/build.sh" all "${tag}"; then
    status=0
  else
    status=$?
  fi
  if [ "${status}" -ne 0 ]; then
    echo "publish: build/upload failed for ${tag} (status ${status})" >&2
    publish-failure "${stack}" "${version}" "${log_file}"
    rm -f "${log_file}" || true
    return "${status}"
  fi

  if publish-artifact-exists "${stack}" "${version}" "${log_file}"; then
    reconcile-report success "${stack}" "${version}"
    rm -f "${log_file}" || true
    return 0
  else
    status=$?
  fi
  echo "publish: artifact verification failed for ${tag} (status ${status})" >&2
  publish-failure "${stack}" "${version}" "${log_file}"
  rm -f "${log_file}" || true
  return "${status}"
}

_is_sourced() {
	# https://unix.stackexchange.com/a/215279
	[ "${#FUNCNAME[@]}" -ge 2 ] \
		&& [ "${FUNCNAME[0]}" = '_is_sourced' ] \
		&& [ "${FUNCNAME[1]}" = 'source' ]
}
if ! _is_sourced; then
  action=$1
  shift 1
  $action "$@"
fi
