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

test_kvrocks_installs_dependencies_with_stack_helper() {
  local root rc
  root="$(mktemp -d)"
  CASE_ROOT="${root}"
  DATA_DIR="${root}/data"
  STACK_VERSION="2.17.0"
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
    dpkg() { printf 'amd64\n'; }
    curl() { :; }
    tar() { :; }
    cd() { :; }
    apt() {
      # Never let the regression test invoke the host package manager.
      exit 100
    }
    install-packages() {
      printf 'install-packages %s\n' "$*" >> "${CASE_ROOT}/commands"
      # Stop at the package-manager boundary; later build steps are irrelevant.
      exit 0
    }
    . "${SCRIPT_DIR}/stacks/kvrocks/build.sh" "${CASE_ROOT}/dist"
  ) > "${root}/out.log" 2>&1
  rc=$?
  if [ "${rc}" -ne 0 ]; then
    echo "  kvrocks did not use install-packages for its build dependencies" >&2
  elif ! grep -Fqx 'install-packages git build-essential cmake libtool python3 libssl-dev' "${root}/commands"; then
    echo "  kvrocks passed an unexpected dependency set to install-packages" >&2
    rc=1
  fi
  report "kvrocks installs build dependencies through the stack helper" "${rc}"
  rm -rf "${root}"
}

test_mysql_strips_only_installed_elf_binaries() {
  local root rc
  root="$(mktemp -d)"
  CASE_ROOT="${root}"
  mkdir -p "${root}/bin"
  cp /bin/true "${root}/bin/mysqld"
  printf '#!/bin/sh\n' > "${root}/bin/mysql_tzinfo_to_sql"
  chmod +x "${root}/bin/mysql_tzinfo_to_sql"
  (
    function . {
      if [ "${1:-}" = "/usr/bin/stack-utils" ]; then
        :
      else
        builtin . "$@"
      fi
    }
    build-stack() { :; }
    . "${SCRIPT_DIR}/stacks/mysql/build.sh"
    strip() {
      printf '%s\n' "$1" >> "${CASE_ROOT}/strip-commands"
    }
    # lz4_decompress is intentionally absent, as in the MySQL 26.10 build.
    strip-mysql-binaries "${CASE_ROOT}/bin"
  ) > "${root}/out.log" 2>&1
  rc=$?
  if [ "${rc}" -ne 0 ]; then
    echo "  stripping installed MySQL binaries failed" >&2
    cat "${root}/out.log" >&2
  elif [ ! -f "${root}/strip-commands" ] || \
      [ "$(cat "${root}/strip-commands")" != "${root}/bin/mysqld" ]; then
    echo "  expected only the installed ELF binary to be stripped" >&2
    cat "${root}/strip-commands" >&2 2>/dev/null || true
    rc=1
  fi
  report "mysql strips only installed ELF binaries" "${rc}"
  rm -rf "${root}"
}

test_mysql_preserves_strip_failure_status() {
  local root rc
  root="$(mktemp -d)"
  CASE_ROOT="${root}"
  mkdir -p "${root}/bin"
  cp /bin/true "${root}/bin/mysqld"
  (
    function . {
      if [ "${1:-}" = "/usr/bin/stack-utils" ]; then
        :
      else
        builtin . "$@"
      fi
    }
    build-stack() { :; }
    . "${SCRIPT_DIR}/stacks/mysql/build.sh"
    strip() { return 23; }
    strip-mysql-binaries "${CASE_ROOT}/bin"
  ) > "${root}/out.log" 2>&1
  rc=$?
  if [ "${rc}" -ne 23 ]; then
    echo "  expected strip status 23, got ${rc}" >&2
    cat "${root}/out.log" >&2
    rc=1
  else
    rc=0
  fi
  report "mysql preserves strip failure status" "${rc}"
  rm -rf "${root}"
}

test_mongodb_exporter_builds_from_source() {
  local root rc
  root="$(mktemp -d)"
  CASE_ROOT="${root}"
  DATA_DIR="${root}/data"
  STACK_VERSION="0.48.0"
  GO_VERSION="1.27.4"
  OS_ARCH="arm64"
  (
    function . {
      case "${1:-}" in
        /usr/bin/stack-utils|init-stack) : ;;
        *) builtin . "$@" ;;
      esac
    }
    build-stack() { build "$@"; }
    generate-stack-path() { :; }
    install-stack() { printf 'install-stack %s\n' "$*" >> "${CASE_ROOT}/commands"; }
    git() { printf 'git %s\n' "$*" >> "${CASE_ROOT}/commands"; }
    make() { printf 'make %s\n' "$*" >> "${CASE_ROOT}/commands"; }
    mv() { printf 'mv %s\n' "$*" >> "${CASE_ROOT}/commands"; }
    curl() { printf 'curl %s\n' "$*" >> "${CASE_ROOT}/commands"; }
    tar() { :; }
    cd() { :; }
    rm() { :; }
    . "${SCRIPT_DIR}/stacks/mongodb_exporter/build.sh" "${CASE_ROOT}/dist"
  ) > "${root}/out.log" 2>&1
  rc=$?
  if [ "${rc}" -ne 0 ]; then
    echo "  mongodb_exporter source build failed" >&2
    cat "${root}/out.log" >&2
  else
    if ! grep -Fqx 'install-stack go 1.27.4' "${root}/commands" || \
        ! grep -Fqx 'git clone --depth 1 --branch v0.48.0 https://github.com/percona/mongodb_exporter.git' "${root}/commands" || \
        ! grep -Fqx 'make build COMPONENT_VERSION=v0.48.0' "${root}/commands" || \
        ! grep -Fqx "mv mongodb_exporter ${root}/data/bin/mongodb_exporter" "${root}/commands"; then
      echo "  mongodb_exporter did not build the tagged source with Go" >&2
      cat "${root}/commands" >&2
      rc=1
    elif grep -q 'releases/download' "${root}/commands"; then
      echo "  mongodb_exporter still depends on a release asset" >&2
      rc=1
    fi
  fi
  report "mongodb_exporter builds from source without release assets" "${rc}"
  rm -rf "${root}"
}

test_mongodb6_amd64_uses_published_ubuntu_archive() {
  local root rc
  root="$(mktemp -d)"
  CASE_ROOT="${root}"
  DATA_DIR="${root}/data"
  OS_ARCH="amd64"
  STACK_VERSION="6.0.30"
  mkdir -p "${root}/fixture/mongodb-linux-x86_64-ubuntu2204-6.0.30/bin" "${root}/work"
  printf 'test-mongod\n' > "${root}/fixture/mongodb-linux-x86_64-ubuntu2204-6.0.30/bin/mongod"
  tar -czf "${root}/mongodb.tgz" -C "${root}/fixture" mongodb-linux-x86_64-ubuntu2204-6.0.30
  (
    set -e
    cd "${root}/work"
    function . {
      if [ "${1:-}" = "/usr/bin/stack-utils" ]; then
        :
      else
        builtin . "$@"
      fi
    }
    build-stack() { build "$@"; }
    generate-stack-path() { :; }
    curl() {
      case "$*" in
        *debian12*)
          printf 'Forbidden\n'
          return 22
          ;;
        *ubuntu2204*)
          cat "${CASE_ROOT}/mongodb.tgz"
          ;;
        *)
          return 2
          ;;
      esac
    }
    . "${SCRIPT_DIR}/stacks/mongodb/build.sh" "${root}/dist"
  ) > "${root}/out.log" 2>&1
  rc=$?
  if [ "${rc}" -ne 0 ] || [ ! -f "${root}/data/bin/mongod" ]; then
    echo "  mongodb 6 amd64 did not use the published Ubuntu 22.04 archive" >&2
    cat "${root}/out.log" >&2
    rc=1
  elif [ "$(cat "${root}/data/bin/mongod")" != "test-mongod" ]; then
    echo "  mongodb 6 amd64 installed unexpected archive contents" >&2
    rc=1
  fi
  report "mongodb 6 amd64 uses the published Ubuntu archive" "${rc}"
  rm -rf "${root}"
}

test_pack_build_keeps_tagged_go_dependencies() {
  local root rc
  root="$(mktemp -d)"
  CASE_ROOT="${root}"
  DATA_DIR="${root}/data"
  STACK_NAME="pack"
  STACK_VERSION="0.40.11"
  GO_VERSION="1.26.11"
  (
    set -e
    function . {
      case "${1:-}" in
        /usr/bin/stack-utils|init-stack) : ;;
        *) builtin . "$@" ;;
      esac
    }
    build-stack() { build "$@"; }
    generate-stack-path() { :; }
    install-stack() { :; }
    curl() { :; }
    tar() { :; }
    cd() { :; }
    rm() { :; }
    go() {
      if [ "${1:-}" = "get" ] && [ "${2:-}" = "-u" ]; then
        echo "go: github.com/buildpacks/lifecycle@v0.21.29 requires go >= 1.27.4" >&2
        return 1
      fi
      if [ "${1:-}" = "mod" ] && [ "${2:-}" = "vendor" ]; then
        touch "${CASE_ROOT}/vendored"
      fi
      if [ "${1:-}" = "build" ] && [ ! -f "${CASE_ROOT}/vendored" ]; then
        echo "go: tagged dependencies were not vendored" >&2
        return 1
      fi
    }
    . "${SCRIPT_DIR}/stacks/pack/build.sh" "${root}/dist"
  ) > "${root}/out.log" 2>&1
  rc=$?
  if [ "${rc}" -ne 0 ]; then
    echo "  pack build upgrades beyond its tagged Go toolchain" >&2
    cat "${root}/out.log" >&2
  fi
  report "pack builds with its tagged Go dependencies" "${rc}"
  rm -rf "${root}"
}

test_clickhouse_build_has_no_stale_workspace_lookup() {
  local root rc
  root="$(mktemp -d)"
  DATA_DIR="${root}/data"
  STACK_VERSION="26.3.64.3"
  (
    set -e
    function . {
      if [ "${1:-}" = "/usr/bin/stack-utils" ]; then
        :
      else
        builtin . "$@"
      fi
    }
    build-stack() { build "$@"; }
    generate-stack-path() { :; }
    curl() { :; }
    tar() { :; }
    mv() { :; }
    rm() { :; }
    . "${SCRIPT_DIR}/stacks/clickhouse/build.sh" "${root}/dist"
  ) > "${root}/out.log" 2>&1
  rc=$?
  if [ "${rc}" -ne 0 ]; then
    echo "  clickhouse build still accesses a stale hard-coded workspace" >&2
    cat "${root}/out.log" >&2
  fi
  report "clickhouse builds without a stale workspace lookup" "${rc}"
  rm -rf "${root}"
}

main() {
  test_mysql_installs_webauthn_build_dependency
  test_kvrocks_installs_dependencies_with_stack_helper
  test_mysql_strips_only_installed_elf_binaries
  test_mysql_preserves_strip_failure_status
  test_mongodb_exporter_builds_from_source
  test_mongodb6_amd64_uses_published_ubuntu_archive
  test_pack_build_keeps_tagged_go_dependencies
  test_clickhouse_build_has_no_stale_workspace_lookup

  echo
  echo "${passed} passed, ${failed} failed"
  [ "${failed}" -eq 0 ]
}

main "$@"
