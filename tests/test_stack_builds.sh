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

test_redis_bootstraps_rust_module_dependencies() {
  local root rc stack case_root case_rc
  root="$(mktemp -d)"
  rc=0
  for stack in redis redis-sentinel; do
    case_root="${root}/${stack}"
    mkdir -p "${case_root}/home"
    (
      set -e
      CASE_ROOT="${case_root}"
      HOME="${case_root}/home"
      STACK_NAME="${stack}"
      STACK_VERSION="8.12.0"
      function . {
        if [ "${1:-}" = "/usr/bin/stack-utils" ]; then
          :
        else
          builtin . "$@"
        fi
      }
      build-stack() { build "$@"; }
      apt-mark() { :; }
      curl() { :; }
      mkdir() { :; }
      tar() { :; }
      rm() { :; }
      grep() { :; }
      sed() { :; }
      dpkg-architecture() { printf 'x86_64-linux-gnu\n'; }
      dpkg() { printf 'amd64\n'; }
      nproc() { printf '2\n'; }
      make() {
        if [ "$#" -eq 5 ] && [ "$1" = "-C" ] && [ "$2" = "/usr/src/redis" ] && \
            [ "$3" = "bootstrap" ] && [ "$4" = "redisearch" ] && [ "$5" = "redisjson" ]; then
          command mkdir -p "${HOME}/.cargo/bin"
          for tool in cargo rustc; do
            printf '#!/bin/sh\n' > "${HOME}/.cargo/bin/${tool}"
            command chmod +x "${HOME}/.cargo/bin/${tool}"
          done
          : > "${CASE_ROOT}/bootstrapped"
          return 0
        fi
        if [ "$#" -eq 5 ] && [ "$1" = "-C" ] && [ "$2" = "/usr/src/redis" ] && \
            [ "$3" = "-j" ] && [ "$4" = "2" ] && [ "$5" = "all" ]; then
          if [ ! -f "${CASE_ROOT}/bootstrapped" ]; then
            echo 'Dependency check failed: cargo is missing' >&2
            return 2
          fi
          if ! command -v cargo > /dev/null || ! command -v rustc > /dev/null; then
            echo 'rustup toolchain is not on PATH' >&2
            return 2
          fi
          return 42
        fi
        echo "unexpected make invocation: $*" >&2
        return 99
      }
      . "${SCRIPT_DIR}/stacks/${stack}/build.sh" "${case_root}/dist"
    ) > "${case_root}/out.log" 2>&1
    case_rc=$?
    if [ "${case_rc}" -ne 42 ]; then
      echo "  ${stack} did not bootstrap its Rust modules before building (rc=${case_rc})" >&2
      cat "${case_root}/out.log" >&2
      rc=1
    fi
  done
  report "redis stacks bootstrap Rust module dependencies" "${rc}"
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

test_mongodb5_is_rejected_before_download() {
  local root rc
  root="$(mktemp -d)"
  CASE_ROOT="${root}"
  DATA_DIR="${root}/data"
  OS_ARCH="amd64"
  OS_FLAVOUR="debian-13"
  STACK_VERSION="5.0.35"
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
    curl() {
      printf 'unexpected download: %s\n' "$*" >> "${CASE_ROOT}/curl-calls"
      return 99
    }
    . "${SCRIPT_DIR}/stacks/mongodb/build.sh" "${root}/dist"
  ) > "${root}/out.log" 2>&1
  rc=$?
  if [ "${rc}" -eq 0 ]; then
    echo "  mongodb 5 was not rejected on Debian 13" >&2
    rc=1
  elif ! grep -q 'not supported' "${root}/out.log"; then
    echo "  mongodb 5 rejection does not explain the unsupported platform" >&2
    cat "${root}/out.log" >&2
    rc=1
  elif [ -e "${root}/curl-calls" ]; then
    echo "  mongodb 5 attempted a download before rejection" >&2
    cat "${root}/curl-calls" >&2
    rc=1
  else
    rc=0
  fi
  report "mongodb 5 is rejected before downloading an incompatible archive" "${rc}"
  rm -rf "${root}"
}

test_rabbitmq_admin_matches_server_distribution() {
  local root rc arch mode expected_arch
  rc=0
  for arch in amd64 arm64; do
    if [ "${arch}" = "amd64" ]; then expected_arch="x86_64"; else expected_arch="aarch64"; fi
    for mode in bundled standalone; do
      root="$(mktemp -d)"
      CASE_ROOT="${root}"
      DATA_DIR="${root}/data"
      PROFILE_DIR="${DATA_DIR}/profile.d"
      META_DIR="${root}/meta"
      TARNAME="${root}/package"
      STACK_NAME="rabbitmq"
      STACK_VERSION="4.4.1"
      OS_ARCH="${arch}"
      RABBITMQADMIN_VERSION="2.30.0"
      mkdir -p "${DATA_DIR}" "${PROFILE_DIR}" "${META_DIR}"
      (
        set -e
        cd "${root}"
        function . {
          if [ "${1:-}" = "/usr/bin/stack-utils" ]; then
            :
          else
            builtin . "$@"
          fi
        }
        build-stack() { build "$@"; }
        generate-stack-path() { :; }
        install-packages() { :; }
        xz() { :; }
        tar() { mkdir -p "rabbitmq_server-${STACK_VERSION}"; }
        cp() {
          case "$*" in
            *rabbitmq_server-${STACK_VERSION}*)
              mkdir -p "${DATA_DIR}/sbin"
              if [ "${mode}" = "bundled" ]; then
                mkdir -p "${DATA_DIR}/plugins/rabbitmq_management-test/priv/www/cli"
                printf 'bundled-admin\n' > "${DATA_DIR}/plugins/rabbitmq_management-test/priv/www/cli/rabbitmqadmin"
              fi
              ;;
            *priv/www/cli/rabbitmqadmin*)
              if [ "${mode}" != "bundled" ]; then
                echo "cp: cannot stat bundled rabbitmqadmin" >&2
                return 1
              fi
              printf 'bundled-admin\n' > "${DATA_DIR}/sbin/rabbitmqadmin"
              ;;
            *)
              return 1
              ;;
          esac
        }
        curl() {
          local output="" url="${*: -1}"
          printf 'curl %s\n' "$*" >> "${CASE_ROOT}/commands"
          while [ "$#" -gt 0 ]; do
            if [ "$1" = "-o" ]; then output="$2"; shift 2; else shift; fi
          done
          case "${url}" in
            *rabbitmq-server-generic-unix-*)
              : > tmp.tar.xz
              ;;
            *rabbitmqadmin-ng*)
              printf '#!/bin/sh\n' > "${output}"
              ;;
            *)
              return 2
              ;;
          esac
        }
        . "${SCRIPT_DIR}/stacks/rabbitmq/build.sh" "${root}/dist"
      ) > "${root}/out.log" 2>&1
      case_rc=$?
      if [ "${case_rc}" -ne 0 ] || [ ! -x "${DATA_DIR}/sbin/rabbitmqadmin" ]; then
        echo "  rabbitmq ${arch}/${mode} did not install rabbitmqadmin" >&2
        cat "${root}/out.log" >&2
        rc=1
      elif [ "${mode}" = "standalone" ] && ! grep -Fqx "curl -fsSL -o ${DATA_DIR}/sbin/rabbitmqadmin https://github.com/rabbitmq/rabbitmqadmin-ng/releases/download/v2.30.0/rabbitmqadmin-2.30.0-${expected_arch}-unknown-linux-gnu" "${root}/commands"; then
        echo "  rabbitmq ${arch} did not use the official standalone admin binary" >&2
        cat "${root}/commands" >&2
        rc=1
      elif [ "${mode}" = "bundled" ] && grep -q 'rabbitmqadmin-ng' "${root}/commands"; then
        echo "  rabbitmq downloaded v2 despite a bundled v1 admin" >&2
        cat "${root}/commands" >&2
        find "${DATA_DIR}" -type f -print >&2
        rc=1
      fi
      rm -rf "${root}"
    done
  done
  report "rabbitmq uses bundled v1 or arch-correct standalone v2 admin" "${rc}"
}

test_jmx_exporter_matches_optional_isolator_availability() {
  local root rc version status
  rc=0
  for version in 1.2.0 1.3.0 9.9.9; do
    case "${version}" in
      1.2.0) status=404 ;;
      1.3.0) status=200 ;;
      9.9.9) status=503 ;;
    esac
    root="$(mktemp -d)"
    CASE_ROOT="${root}"
    DATA_DIR="${root}/data"
    STACK_VERSION="${version}"
    JMX_TEST_ISOLATOR_STATUS="${status}"
    (
      set -e
      cd "${root}"
      function . {
        if [ "${1:-}" = "/usr/bin/stack-utils" ]; then
          :
        else
          builtin . "$@"
        fi
      }
      build-stack() { build "$@"; }
      generate-stack-path() { :; }
      tar() { :; }
      mv() { :; }
      curl() {
        local output="" url="${*: -1}"
        if [[ "$*" == *--head* ]]; then
          printf '%s\n' "${JMX_TEST_ISOLATOR_STATUS}"
          return 0
        fi
        while [ "$#" -gt 0 ]; do
          if [ "$1" = "-o" ]; then output="$2"; shift 2; else shift; fi
        done
        case "${url}" in
          *jmx_prometheus_isolator_javaagent*)
            if [ "${JMX_TEST_ISOLATOR_STATUS}" != "200" ]; then
              echo "curl: (22) isolator returned ${JMX_TEST_ISOLATOR_STATUS}" >&2
              return 22
            fi
            printf 'isolator\n' > "${output}"
            ;;
          *)
            printf 'required-download\n' > "${output}"
            ;;
        esac
      }
      . "${SCRIPT_DIR}/stacks/jmx_exporter/build.sh" "${root}/dist"
    ) > "${root}/out.log" 2>&1
    case_rc=$?
    if [ "${status}" = "503" ]; then
      if [ "${case_rc}" -eq 0 ] || ! grep -q '503' "${root}/out.log"; then
        echo "  jmx exporter did not fail clearly on isolator probe HTTP 503" >&2
        cat "${root}/out.log" >&2
        rc=1
      fi
    elif [ "${case_rc}" -ne 0 ]; then
      echo "  jmx exporter ${version} failed with optional isolator HTTP ${status}" >&2
      cat "${root}/out.log" >&2
      rc=1
    elif [ "${status}" = "404" ] && [ -e "${DATA_DIR}/jmx_prometheus_isolator_javaagent.jar" ]; then
      echo "  jmx exporter ${version} installed a non-existent isolator" >&2
      rc=1
    elif [ "${status}" = "200" ] && [ ! -f "${DATA_DIR}/jmx_prometheus_isolator_javaagent.jar" ]; then
      echo "  jmx exporter ${version} dropped the published isolator" >&2
      rc=1
    fi
    rm -rf "${root}"
  done
  report "jmx exporter follows optional isolator release availability" "${rc}"
}

test_valkey_patches_the_extracted_jemalloc_makefile() {
  local root rc
  root="$(mktemp -d)"
  CASE_ROOT="${root}"
  DATA_DIR="${root}/data"
  STACK_VERSION="7.2.16"
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
    mkdir() { :; }
    curl() { :; }
    tar() { :; }
    rm() { :; }
    grep() { :; }
    apt-mark() { :; }
    dpkg() { printf 'amd64\n'; }
    dpkg-architecture() { printf 'x86_64-linux-gnu\n'; }
    sed() {
      printf 'sed %s\n' "$*" >> "${CASE_ROOT}/commands"
      case "$*" in
        */usr/src/valkey/deps/Makefile*)
          exit 0
          ;;
        *deps/Makefile*)
          return 2
          ;;
        *)
          return 0
          ;;
      esac
    }
    . "${SCRIPT_DIR}/stacks/valkey/build.sh" "${root}/dist"
  ) > "${root}/out.log" 2>&1
  rc=$?
  if [ "${rc}" -ne 0 ]; then
    echo "  valkey did not patch /usr/src/valkey/deps/Makefile" >&2
    cat "${root}/out.log" >&2
  fi
  report "valkey patches the extracted jemalloc Makefile" "${rc}"
  rm -rf "${root}"
}

test_php_pic_option_matches_configure_capability() {
  local root rc version with_pic
  rc=0
  for version in 8.5.1 8.6.0; do
    root="$(mktemp -d)"
    CASE_ROOT="${root}"
    STACK_VERSION="${version}"
    META_DIR="${root}/meta"
    mkdir -p "${META_DIR}"
    : > "${META_DIR}/dependencies"
    if [ "${version}" = "8.5.1" ]; then with_pic=1; else with_pic=0; fi
    cat > "${root}/configure" <<'EOF'
#!/bin/bash
if [ "${1:-}" = "--help" ]; then
  if [ "${PHP_TEST_WITH_PIC}" = "1" ]; then
    printf '%s\n' '  --with-pic              Try to use only PIC/non-PIC objects'
  fi
  exit 0
fi
printf '%s\n' "$*" > "${CASE_ROOT}/configure-args"
exit 42
EOF
    chmod +x "${root}/configure"
    (
      set -e
      cd "${root}"
      install-packages() { :; }
      apt-mark() { :; }
      curl() { :; }
      tar() { :; }
      mv() { :; }
      cp() { :; }
      ln() { :; }
      mkdir() { :; }
      chown() { :; }
      chmod() { :; }
      cd() { :; }
      dpkg-architecture() { printf 'x86_64-linux-gnu\n'; }
      PHP_TEST_WITH_PIC="${with_pic}"
      export CASE_ROOT PHP_TEST_WITH_PIC
      . "${SCRIPT_DIR}/stacks/php/make.sh"
    ) > "${root}/out.log" 2>&1
    case_rc=$?
    if [ "${case_rc}" -ne 42 ]; then
      echo "  php ${version} did not reach the configure boundary" >&2
      cat "${root}/out.log" >&2
      rc=1
    elif [ "${version}" = "8.5.1" ] && ! grep -q -- '--with-pic' "${root}/configure-args"; then
      echo "  php ${version} lost its supported --with-pic option" >&2
      cat "${root}/configure-args" >&2
      rc=1
    elif [ "${version}" = "8.6.0" ] && grep -q -- '--with-pic' "${root}/configure-args"; then
      echo "  php ${version} still uses the removed --with-pic option" >&2
      cat "${root}/configure-args" >&2
      rc=1
    fi
    rm -rf "${root}"
  done
  report "php keeps --with-pic only when configure supports it" "${rc}"
}

test_php_cleanup_ignores_dpkg_diversions() {
  local root rc
  root="$(mktemp -d)"
  CASE_ROOT="${root}"
  STACK_VERSION="8.6.0"
  META_DIR="${root}/meta"
  mkdir -p "${META_DIR}"
  : > "${META_DIR}/dependencies"
  cat > "${root}/configure" <<'EOF'
#!/bin/bash
if [ "${1:-}" = "--help" ]; then
  exit 0
fi
exit 0
EOF
  chmod +x "${root}/configure"
  mkdir -p "${root}/bin"
  cat > "${root}/bin/apt-mark" <<'EOF'
#!/bin/bash
if [ "${1:-}" = "manual" ]; then
  printf '%s\n' "$*" >> "${CASE_ROOT}/apt-manual"
fi
EOF
  cat > "${root}/bin/dpkg-query" <<'EOF'
#!/bin/bash
printf 'libreadline8t64: /usr/lib/x86_64-linux-gnu/libreadline.so.8\n'
printf 'diversion by libreadline8t64: /usr/lib/x86_64-linux-gnu/libreadline.so.8\n'
printf 'diversion from libreadline8t64: /usr/lib/x86_64-linux-gnu/libreadline.so.8\n'
printf 'diversion to libreadline8t64: /usr/lib/x86_64-linux-gnu/libreadline.so.8\n'
EOF
  chmod +x "${root}/bin/apt-mark" "${root}/bin/dpkg-query"
  (
    set -e
    cd "${root}"
    PATH="${root}/bin:${PATH}"
    install-packages() { :; }
    apt-get() { return 43; }
    curl() { :; }
    tar() { :; }
    mv() { :; }
    cp() { :; }
    ln() { :; }
    mkdir() { :; }
    chown() { :; }
    chmod() { :; }
    cd() { :; }
    make() { :; }
    rm() { :; }
    dpkg-architecture() { printf 'x86_64-linux-gnu\n'; }
    find() {
      if [[ "$*" == *'-exec ldd'* ]]; then
        printf 'libreadline.so.8 => /lib/x86_64-linux-gnu/libreadline.so.8\n'
      fi
    }
    export CASE_ROOT PATH
    . "${SCRIPT_DIR}/stacks/php/make.sh"
  ) > "${root}/out.log" 2>&1
  rc=$?
  if [ "${rc}" -ne 43 ]; then
    echo "  php cleanup did not reach the package-manager boundary" >&2
    cat "${root}/out.log" >&2
    rc=1
  elif [ "$(tail -n 1 "${root}/apt-manual")" != "manual libreadline8t64" ]; then
    echo "  php cleanup passed dpkg diversion text to apt-mark" >&2
    cat "${root}/apt-manual" >&2
    rc=1
  elif ! grep -Fxq 'libargon2-1' "${META_DIR}/dependencies" \
      || ! grep -Fxq 'libpcre2-8-0' "${META_DIR}/dependencies" \
      || grep -Fxq 'libpcre3-dev' "${META_DIR}/dependencies"; then
    echo "  php package has incorrect Argon2/PCRE2 runtime dependencies" >&2
    cat "${META_DIR}/dependencies" >&2
    rc=1
  else
    rc=0
  fi
  report "php cleanup ignores dpkg diversion records" "${rc}"
  rm -rf "${root}"
}

test_node_exporter_retries_until_archive_is_valid() {
  local root rc mode attempts
  rc=0
  for mode in recover persistent; do
    root="$(mktemp -d)"
    CASE_ROOT="${root}"
    DATA_DIR="${root}/data"
    OS_ARCH="arm64"
    STACK_VERSION="1.13.1"
    NODE_TEST_MODE="${mode}"
    mkdir -p "${root}/fixture/node_exporter-1.13.1.linux-arm64" "${root}/work"
    printf 'node-exporter-test\n' > "${root}/fixture/node_exporter-1.13.1.linux-arm64/node_exporter"
    tar -czf "${root}/release.tar.gz" -C "${root}/fixture" node_exporter-1.13.1.linux-arm64
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
      upx() { :; }
      sleep() { :; }
      curl() {
        local output="" count
        printf '%s\n' "$*" >> "${CASE_ROOT}/curl-calls"
        count=$(wc -l < "${CASE_ROOT}/curl-calls")
        case "$*" in
          *"-fsSL"*"--retry 6"*"--retry-all-errors"*"--retry-delay 2"*"--retry-max-time 120"*)
            while [ "$#" -gt 0 ]; do
              if [ "$1" = "-o" ]; then output="$2"; shift 2; else shift; fi
            done
            if [ "${NODE_TEST_MODE}" = "recover" ] && [ "${count}" -ge 2 ]; then
              command cp "${CASE_ROOT}/release.tar.gz" "${output}"
            else
              printf '<html>not a gzip archive</html>\n' > "${output}"
            fi
            ;;
          *)
            # Reproduce the original pipeline: an HTTP 200 HTML body is piped
            # directly to tar because no content validation exists.
            printf '<html>not a gzip archive</html>\n'
            ;;
        esac
      }
      . "${SCRIPT_DIR}/stacks/node_exporter/build.sh" "${root}/dist"
    ) > "${root}/out.log" 2>&1
    case_rc=$?
    attempts=$(wc -l < "${root}/curl-calls")
    if [ "${mode}" = "recover" ]; then
      if [ "${case_rc}" -ne 0 ] || [ ! -f "${DATA_DIR}/bin/node_exporter" ] || [ "${attempts}" -ne 2 ]; then
        echo "  node_exporter did not recover after an HTTP 200 non-gzip response (rc=${case_rc}, attempts=${attempts})" >&2
        cat "${root}/out.log" >&2
        rc=1
      fi
    else
      if [ "${case_rc}" -eq 0 ] || [ "${attempts}" -ne 3 ]; then
        echo "  node_exporter did not stop after three invalid archives (rc=${case_rc}, attempts=${attempts})" >&2
        cat "${root}/out.log" >&2
        rc=1
      fi
    fi
    rm -rf "${root}"
  done
  report "node exporter retries until the downloaded archive is valid" "${rc}"
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

test_haproxy_builds_stable_source_with_production_features() {
  local root rc options expected_commands
  root="$(mktemp -d)"
  CASE_ROOT="${root}"
  DATA_DIR="${root}/data"
  PROFILE_DIR="${DATA_DIR}/profile.d"
  STACK_NAME="haproxy"
  STACK_VERSION="3.4.0"
  (
    set -e
    cd "${root}"
    mkdir -p "${DATA_DIR}" "${PROFILE_DIR}"
    function . {
      if [ "${1:-}" = "/usr/bin/stack-utils" ]; then
        :
      else
        builtin . "$@"
      fi
    }
    build-stack() { build "$@"; }
    install-packages() {
      printf 'install-packages %s\n' "$*" >> "${CASE_ROOT}/commands"
    }
    nproc() { printf '4\n'; }
    curl() {
      printf 'curl %s\n' "$*" >> "${CASE_ROOT}/commands"
      : > haproxy.tar.gz
    }
    tar() {
      printf 'tar %s\n' "$*" >> "${CASE_ROOT}/commands"
      mkdir -p "haproxy-${STACK_VERSION}"
    }
    make() {
      local arg prefix=""
      printf 'make %s\n' "$*" >> "${CASE_ROOT}/commands"
      if [ "${1:-}" = "install" ]; then
        for arg in "$@"; do
          case "${arg}" in
            PREFIX=*) prefix="${arg#PREFIX=}" ;;
          esac
        done
        mkdir -p "${prefix}/sbin"
        printf '#!/bin/sh\necho "HAProxy version 3.4.0"\n' > "${prefix}/sbin/haproxy"
        chmod +x "${prefix}/sbin/haproxy"
      fi
    }
    . "${SCRIPT_DIR}/stacks/haproxy/build.sh" "${root}/dist"
  ) > "${root}/out.log" 2>&1
  rc=$?
  options='TARGET=linux-glibc USE_GETADDRINFO=1 USE_OPENSSL=1 USE_LUA=1 LUA_LIB_NAME=lua5.4 USE_PCRE2=1 USE_PCRE2_JIT=1 USE_PROMEX=1 USE_ZLIB=1'
  expected_commands="install-packages libssl-dev libpcre2-dev liblua5.4-dev zlib1g-dev
curl -fsSL -o haproxy.tar.gz https://github.com/haproxy/haproxy/archive/refs/tags/v3.4.0.tar.gz
tar -xzf haproxy.tar.gz
make -j 4 ${options}
make install ${options} PREFIX=${root}/data"
  if [ "${rc}" -ne 0 ]; then
    echo "  haproxy source build failed" >&2
    cat "${root}/out.log" >&2
  elif [ ! -x "${root}/data/sbin/haproxy" ]; then
    echo "  haproxy was not installed into the stack payload" >&2
    rc=1
  elif ! grep -Fqx 'export PATH="/opt/drycc/haproxy/sbin:$PATH"' "${root}/data/profile.d/haproxy.sh"; then
    echo "  haproxy profile does not expose the sbin directory" >&2
    rc=1
  elif ! diff -u <(printf '%s\n' "${expected_commands}") "${root}/commands"; then
    echo "  haproxy used unexpected download, dependency, or build commands" >&2
    rc=1
  fi
  report "haproxy builds stable source with production features" "${rc}"
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
  test_redis_bootstraps_rust_module_dependencies
  test_mysql_strips_only_installed_elf_binaries
  test_mysql_preserves_strip_failure_status
  test_mongodb_exporter_builds_from_source
  test_mongodb6_amd64_uses_published_ubuntu_archive
  test_mongodb5_is_rejected_before_download
  test_rabbitmq_admin_matches_server_distribution
  test_jmx_exporter_matches_optional_isolator_availability
  test_valkey_patches_the_extracted_jemalloc_makefile
  test_php_pic_option_matches_configure_capability
  test_php_cleanup_ignores_dpkg_diversions
  test_node_exporter_retries_until_archive_is_valid
  test_pack_build_keeps_tagged_go_dependencies
  test_haproxy_builds_stable_source_with_production_features
  test_clickhouse_build_has_no_stale_workspace_lookup

  echo
  echo "${passed} passed, ${failed} failed"
  [ "${failed}" -eq 0 ]
}

main "$@"
