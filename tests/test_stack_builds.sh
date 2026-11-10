#!/usr/bin/env bash
# Focused regression tests for stack build dependency setup.
#
# The real build functions run with external commands replaced by recorders.
# No network access, package installation, or writes outside the case's temp
# directory are performed.
#
# Run: bash tests/test_stack_builds.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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

test_mysql_installs_webauthn_build_dependency() {
  local root rc
  root="$(mktemp -d)"
  CASE_ROOT="${root}"
  STACK_VERSION="26.10.0"
  OS_ARCH="amd64"
  (
    function . {
      if [ "${1:-}" = "/usr/bin/stack-utils" ]; then
        :
      else
        builtin . "$@"
      fi
    }
    build-stack() { build "$@"; }
    generate-stack-path() { :; }
    install-packages() {
      local package found=1
      printf 'install-packages %s\n' "$*" >> "${CASE_ROOT}/commands"
      for package in "$@"; do
        if [ "${package}" = "libudev-dev" ]; then
          found=0
        fi
      done
      # Stop at the package-manager boundary: the assertion is about the
      # dependency set, and later build commands are irrelevant here.
      exit "${found}"
    }
    . "${SCRIPT_DIR}/stacks/mysql/build.sh" "${CASE_ROOT}/dist"
  ) > "${root}/out.log" 2>&1
  rc=$?
  if [ "${rc}" -ne 0 ]; then
    echo "  libudev-dev is missing from the MySQL build dependencies" >&2
  fi
  report "mysql installs the WebAuthn build dependency" "${rc}"
  rm -rf "${root}"
}

main() {
  test_mysql_installs_webauthn_build_dependency

  echo
  echo "${passed} passed, ${failed} failed"
  [ "${failed}" -eq 0 ]
}

main "$@"
