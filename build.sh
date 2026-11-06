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


function reconcile-report() {
  # Report a per-item build result to GitHub: "alert" creates a
  # deduplicated issue for a failed build; "success" records the build
  # (a stack@version tag pointing at the built commit) and closes the
  # open failure issue. Reporting problems are logged but never change
  # the reconcile exit status.
  local action="${1:?action is required}"
  local stack="${2:?stack is required}"
  local version="${3:?version is required}"
  [ -n "${GITHUB_TOKEN:-}" ] || return 0
  local report_args=("${action}" --stack "${stack}" --version "${version}")
  if [ "${action}" = "alert" ]; then
    report_args+=(--pipeline-url "${CI_PIPELINE_URL:-}")
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


function reconcile-clean() {
  # Clean old OSS objects after a successful reconcile run. Each matrix
  # leg removes only its own arch, so amd64/arm64 never overlap. Dry-run
  # mode is always non-destructive; the cron configuration opts into
  # real deletion with CLEANER_DRY_RUN=0.
  local clean_args=(-n "${CLEANER_KEEP_COUNT:-2}" --arch auto)
  if [ "${RECONCILE_DRY_RUN:-}" = "1" ] || [ "${CLEANER_DRY_RUN:-}" = "1" ]; then
    clean_args+=(--dry-run)
  else
    clean_args+=(--confirm)
  fi
  echo "reconcile: cleaning old OSS objects (keep=${CLEANER_KEEP_COUNT:-2} per series)"
  if ! podman run --rm \
    --env OSS_ENDPOINT="${OSS_ENDPOINT:-}" \
    --env OSS_ACCESS_KEY_ID="${OSS_ACCESS_KEY_ID:-}" \
    --env OSS_ACCESS_KEY_SECRET="${OSS_ACCESS_KEY_SECRET:-}" \
    -v "${CURRENT_DIR}":"${CURRENT_DIR}" \
    -w "${CURRENT_DIR}" \
    "${BUILDPACK_DEP_IMAGE}" \
    python3 scripts/cleaner.py oss-stacks "${clean_args[@]}"; then
    echo "reconcile: cleanup failed" >&2
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
  local ok=0 failed=0
  while read -r item; do
    [ -n "${item}" ] || continue
    echo "reconcile: building ${item}"
    # A dedicated process per item so set -e keeps its normal semantics
    # inside build/upload (an if-context would disable it).
    if SKIP_CREATE_BUILDPACK_DEP=1 bash "${CURRENT_DIR}/build.sh" all "${item}"; then
      ok=$((ok + 1))
      reconcile-report success "${item%@*}" "${item#*@}"
    else
      failed=$((failed + 1))
      echo "reconcile: failed to build ${item}" >&2
      reconcile-report alert "${item%@*}" "${item#*@}"
    fi
  done <<< "${plan}"
  echo "reconcile: done, ok=${ok} failed=${failed}"
  if [ "${failed}" -ne 0 ]; then
    echo "reconcile: skipping OSS cleanup because builds failed" >&2
    return 1
  fi
  reconcile-clean
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
