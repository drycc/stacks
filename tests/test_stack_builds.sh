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

run_cloudbeaver_case() {
  local root="$1" arch="$2"
  mkdir -p "${root}/work" "${root}/data/profile.d"
  CASE_ROOT="${root}"
  DATA_DIR="${root}/data"
  PROFILE_DIR="${root}/data/profile.d"
  STACK_VERSION="26.2.0"
  OS_ARCH="${arch}"
  CLOUDBEAVER_UPSTREAM_RC="${3:-0}"
  (
    record() {
      printf '%s\n' "$*" >> "${CASE_ROOT}/commands"
    }

    # Intercept only the absolute utility include and init-stack. Other dot
    # invocations still source the real script under test.
    function . {
      case "${1:-}" in
        /usr/bin/stack-utils) set -e ;;
        init-stack) : ;;
        *) builtin . "$@" ;;
      esac
    }

    cd() {
      case "${1:-}" in
        /opt/drycc|/opt/drycc/) builtin cd "${CASE_ROOT}/work" ;;
        *) builtin cd "$@" ;;
      esac
    }

    build-stack() { build "$@"; }
    install-packages() { record "install-packages $*"; }
    install-stack() { record "install-stack $*"; }
    mvn() { record "mvn $*"; }
    yarn() { record "yarn $*"; }
    corepack() { record "corepack $*"; }
    apt-key() { record "apt-key $*"; }
    tee() { cat > /dev/null; }
    tar() { record "tar $*"; }

    curl() {
      local output=""
      record "curl $*"
      while [ "$#" -gt 0 ]; do
        case "$1" in
          -o|--output)
            output="$2"
            shift 2
            ;;
          *) shift ;;
        esac
      done
      if [ -n "${output}" ]; then
        : > "${output}"
      fi
    }

    git() {
      local repo name
      record "git $*"
      if [ "${1:-}" = "clone" ]; then
        repo="${!#}"
        name="${repo##*/}"
        name="${name%.git}"
        mkdir -p "${name}"
        if [ "${name}" = "cloudbeaver" ]; then
          mkdir -p "${name}/deploy"
          cat > "${name}/deploy/build.sh" <<'EOF'
#!/usr/bin/env bash
mkdir -p cloudbeaver
echo payload > cloudbeaver/payload
exit "${CLOUDBEAVER_UPSTREAM_RC:-0}"
EOF
          chmod +x "${name}/deploy/build.sh"
        fi
      fi
    }

    export CLOUDBEAVER_UPSTREAM_RC
    . "${SCRIPT_DIR}/stacks/cloudbeaver/build.sh" "${CASE_ROOT}/dist"
  ) > "${root}/out.log" 2>&1
  echo "$?" > "${root}/rc"
}

test_cloudbeaver_checkouts_requested_release() {
  local root="$1" rc=0
  [ "$(cat "${root}/rc")" -eq 0 ] || rc=1
  grep -Fx 'git clone --depth 1 --branch 26.2.0 https://github.com/dbeaver/dbeaver.git' \
    "${root}/commands" > /dev/null || {
    echo "  DBeaver 26.2.0 tag was not cloned" >&2
    rc=1
  }
  grep -Fx 'git clone --depth 1 --branch 26.2.0 https://github.com/dbeaver/cloudbeaver.git' \
    "${root}/commands" > /dev/null || {
    echo "  CloudBeaver 26.2.0 tag was not cloned" >&2
    rc=1
  }
  grep -Fx 'git clone --depth 1 --branch 26.2.0 https://github.com/dbeaver/dbeaver-common.git' \
    "${root}/commands" > /dev/null || {
    echo "  dbeaver-common 26.2.0 tag was not cloned" >&2
    rc=1
  }
  report "cloudbeaver checks out the requested release tags" "${rc}"
}

test_cloudbeaver_uses_upstream_node_yarn_toolchain() {
  local root="$1" rc=0
  grep -Fx 'curl -fsSL -o node.tar.xz https://nodejs.org/dist/v24.13.1/node-v24.13.1-linux-x64.tar.xz' \
    "${root}/commands" > /dev/null || {
    echo "  upstream Node 24.13.1 was not downloaded" >&2
    rc=1
  }
  grep -Fx 'corepack enable' "${root}/commands" > /dev/null || {
    echo "  Corepack was not enabled" >&2
    rc=1
  }
  grep -Fx 'corepack prepare yarn@4.14.1 --activate' "${root}/commands" > /dev/null || {
    echo "  upstream Yarn 4.14.1 was not activated" >&2
    rc=1
  }
  report "cloudbeaver uses the upstream Node and Yarn toolchain" "${rc}"
}

test_cloudbeaver_node_download_matches_arm64() {
  local root="$1" rc=0
  grep -Fx 'curl -fsSL -o node.tar.xz https://nodejs.org/dist/v24.13.1/node-v24.13.1-linux-arm64.tar.xz' \
    "${root}/commands" > /dev/null || {
    echo "  Node download did not use the arm64 archive" >&2
    rc=1
  }
  report "cloudbeaver Node download matches arm64" "${rc}"
}

test_cloudbeaver_upstream_build_failure_is_fatal() {
  local root rc=0
  root="$(mktemp -d)"
  run_cloudbeaver_case "${root}" amd64 42
  if [ "$(cat "${root}/rc")" -eq 0 ]; then
    echo "  CloudBeaver returned success after its upstream build failed" >&2
    rc=1
  elif [ -e "${root}/data/profile.d/cloudbeaver.sh" ]; then
    echo "  CloudBeaver kept running after its upstream build failed" >&2
    rc=1
  fi
  report "cloudbeaver upstream build failure is fatal" "${rc}"
  rm -rf "${root}"
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

test_seaweedfs_csi_failure_is_fatal() {
  local root rc=0
  root="$(mktemp -d)"
  mkdir -p "${root}/work" "${root}/data/profile.d"
  CASE_ROOT="${root}"
  DATA_DIR="${root}/data"
  PROFILE_DIR="${root}/data/profile.d"
  STACK_VERSION="3.99"
  GO_VERSION="1.25"
  GOPATH="${root}/gopath"
  (
    cd "${CASE_ROOT}/work"
    record() {
      printf '%s\n' "$*" >> "${CASE_ROOT}/commands"
    }
    function . {
      case "${1:-}" in
        /usr/bin/stack-utils) set -e ;;
        init-stack) : ;;
        *) builtin . "$@" ;;
      esac
    }
    build-stack() { build "$@"; }
    generate-stack-path() { :; }
    install-stack() { record "install-stack $*"; }

    curl() {
      record "curl $*"
      case "$*" in
        */releases)
          printf 'x/seaweedfs/seaweedfs-csi-driver/releases/tag/v1.2.3"\n'
          ;;
      esac
    }
    tar() {
      record "tar $*"
      mkdir -p "seaweedfs-${STACK_VERSION}/weed"
    }
    go() {
      record "go $*"
      if [ "${1:-}" = "install" ]; then
        mkdir -p "${GOPATH}/bin"
        echo weed > "${GOPATH}/bin/weed"
      fi
    }
    git() {
      record "git $*"
      if [ "${1:-}" = "clone" ]; then
        mkdir -p "${!#}"
      else
        printf 'abcdef0\n'
      fi
    }
    make() {
      record "make $*"
      return 42
    }
    upx() {
      record "upx $*"
      return 0
    }

    . "${SCRIPT_DIR}/stacks/seaweedfs/build.sh" "${CASE_ROOT}/dist"
  ) > "${root}/out.log" 2>&1
  if [ "$?" -eq 0 ]; then
    echo "  SeaweedFS returned success after the CSI build failed" >&2
    rc=1
  fi
  if grep -E '^upx ' "${root}/commands" > /dev/null 2>&1; then
    echo "  SeaweedFS ran UPX after the CSI build failed" >&2
    rc=1
  fi
  report "seaweedfs CSI build failure is fatal" "${rc}"
  rm -rf "${root}"
}

main() {
  local amd64_root arm64_root
  amd64_root="$(mktemp -d)"
  arm64_root="$(mktemp -d)"
  run_cloudbeaver_case "${amd64_root}" amd64
  run_cloudbeaver_case "${arm64_root}" arm64

  test_cloudbeaver_checkouts_requested_release "${amd64_root}"
  test_cloudbeaver_uses_upstream_node_yarn_toolchain "${amd64_root}"
  test_cloudbeaver_node_download_matches_arm64 "${arm64_root}"
  test_cloudbeaver_upstream_build_failure_is_fatal
  test_mysql_installs_webauthn_build_dependency
  test_seaweedfs_csi_failure_is_fatal

  rm -rf "${amd64_root}" "${arm64_root}"
  echo
  echo "${passed} passed, ${failed} failed"
  [ "${failed}" -eq 0 ]
}

main "$@"
