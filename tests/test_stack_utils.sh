#!/usr/bin/env bash
# tests/test_stack_utils.sh
#
# Empty-payload guard tests for scripts/stack-utils.
#
# validate-stack-data must reject any build whose DATA_DIR contains nothing
# but scaffolding (empty directories and data/profile.d), so a failed build
# can no longer be packaged and uploaded as an empty tar.gz. build-stack must
# call it after build and before generate-stack-dependencies/package.
#
# Run: bash tests/test_stack_utils.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACK_UTILS="${SCRIPT_DIR}/scripts/stack-utils"

passed=0
failed=0

report() {
  local name="$1" rc="$2"
  if [ "${rc}" -eq 0 ]; then
    echo "PASS: ${name}"
    passed=$((passed + 1))
  else
    echo "FAIL: ${name}"
    failed=$((failed + 1))
  fi
}

# Reproduce what generate-stack-template leaves behind, plus the empty bin
# directory a failed build (e.g. tikv) typically creates before downloading.
make_scaffold() {
  local root="$1"
  mkdir -p "${root}/data/bin" "${root}/data/profile.d" "${root}/meta"
  touch "${root}/meta/dependencies" "${root}/meta/preinstall" "${root}/meta/postinstall"
  printf 'export PATH="/opt/drycc/teststack/bin:$PATH"\n' > "${root}/data/profile.d/teststack.sh"
}

# Prepare an isolated environment inside a subshell: source stack-utils the
# same way stack build.sh scripts do, then redirect the /workspace paths into
# the case's temp directory. Must be the first command inside the subshell.
setup_case() {
  export STACK_NAME="teststack"
  export STACK_VERSION="1.0.0"
  # shellcheck source=/dev/null
  . "${STACK_UTILS}"
  export DATA_DIR="${CASE_ROOT}/data"
  export META_DIR="${CASE_ROOT}/meta"
  export PROFILE_DIR="${CASE_ROOT}/data/profile.d"
}

# Fail fast with a clear message while the guard does not exist yet.
require_guard() {
  if ! declare -F validate-stack-data > /dev/null; then
    echo "  validate-stack-data is not defined" >&2
    exit 1
  fi
}

# Replace packaging steps with recorders so tests can observe whether the
# pipeline moved past validation. Must run after setup_case.
mock_packaging() {
  generate-stack-dependencies() { :; }
  generate-stack-package() { touch "${CASE_ROOT}/pkg.called"; }
}

# A payload containing only profile.d and empty directories must be rejected.
test_scaffold_only_payload_is_rejected() {
  local root rc=0
  root="$(mktemp -d)"
  make_scaffold "${root}"
  CASE_ROOT="${root}"
  (
    setup_case
    require_guard
    if validate-stack-data > /dev/null 2>&1; then
      echo "  accepted a payload containing only profile.d and empty directories" >&2
      exit 1
    fi
    exit 0
  ) || rc=$?
  rm -rf "${root}"
  report "scaffold-only payload is rejected" "${rc}"
}

# A build failure masked by a successful trailing rm -rf (the tikv/grafana
# pattern: set -e is disabled inside build by "build || exit 1", the last
# command succeeds, build returns 0) must still abort the pipeline.
test_masked_build_failure_is_rejected() {
  local root rc=0
  root="$(mktemp -d)"
  make_scaffold "${root}"
  CASE_ROOT="${root}"
  (
    setup_case
    mock_packaging
    build() {
      mkdir -p "${DATA_DIR}/bin"
      false # download fails, but set -e is off inside build
      rm -rf "${CASE_ROOT}/nonexistent-download" # cleanup succeeds, build returns 0
    }
    build-stack "${CASE_ROOT}/dist"
  ) || rc=$?
  if [ "${rc}" -eq 0 ]; then
    echo "  build-stack exited 0 after a masked build failure" >&2
    report "masked build failure is rejected" 1
  elif [ -e "${root}/pkg.called" ]; then
    echo "  generate-stack-package ran despite an empty payload" >&2
    report "masked build failure is rejected" 1
  else
    report "masked build failure is rejected" 0
  fi
  rm -rf "${root}"
}

# A regular payload file under data/bin must pass validation.
test_regular_file_payload_is_accepted() {
  local root rc=0
  root="$(mktemp -d)"
  make_scaffold "${root}"
  CASE_ROOT="${root}"
  (
    setup_case
    require_guard
    echo payload > "${DATA_DIR}/bin/teststack"
    validate-stack-data || {
      echo "  rejected a regular payload file" >&2
      exit 1
    }
    exit 0
  ) || rc=$?
  rm -rf "${root}"
  report "regular file payload is accepted" "${rc}"
}

# A payload outside bin (e.g. data/lib) must pass validation.
test_payload_outside_bin_is_accepted() {
  local root rc=0
  root="$(mktemp -d)"
  make_scaffold "${root}"
  CASE_ROOT="${root}"
  (
    setup_case
    require_guard
    mkdir -p "${DATA_DIR}/lib"
    echo payload > "${DATA_DIR}/lib/libdemo.so"
    validate-stack-data || {
      echo "  rejected a payload file outside bin" >&2
      exit 1
    }
    exit 0
  ) || rc=$?
  rm -rf "${root}"
  report "payload outside bin is accepted" "${rc}"
}

# A symlink payload must pass validation.
test_symlink_payload_is_accepted() {
  local root rc=0
  root="$(mktemp -d)"
  make_scaffold "${root}"
  CASE_ROOT="${root}"
  (
    setup_case
    require_guard
    echo payload > "${DATA_DIR}/bin/real"
    ln -s real "${DATA_DIR}/bin/link"
    validate-stack-data || {
      echo "  rejected a symlink payload" >&2
      exit 1
    }
    exit 0
  ) || rc=$?
  rm -rf "${root}"
  report "symlink payload is accepted" "${rc}"
}

# Regression guard: a valid build must still reach generate-stack-package.
test_valid_build_still_packages() {
  local root rc=0
  root="$(mktemp -d)"
  make_scaffold "${root}"
  CASE_ROOT="${root}"
  (
    setup_case
    mock_packaging
    build() {
      mkdir -p "${DATA_DIR}/bin"
      echo payload > "${DATA_DIR}/bin/teststack"
    }
    build-stack "${CASE_ROOT}/dist" || {
      echo "  build-stack failed for a valid build" >&2
      exit 1
    }
    [ -e "${CASE_ROOT}/pkg.called" ] || {
      echo "  generate-stack-package was not called for a valid build" >&2
      exit 1
    }
    exit 0
  ) || rc=$?
  rm -rf "${root}"
  report "valid build still packages" "${rc}"
}

main() {
  test_scaffold_only_payload_is_rejected
  test_masked_build_failure_is_rejected
  test_regular_file_payload_is_accepted
  test_payload_outside_bin_is_accepted
  test_symlink_payload_is_accepted
  test_valid_build_still_packages

  echo
  echo "${passed} passed, ${failed} failed"
  [ "${failed}" -eq 0 ]
}

main "$@"
