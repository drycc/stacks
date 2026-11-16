#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  local make_options=(
    TARGET=linux-glibc
    USE_GETADDRINFO=1
    USE_OPENSSL=1
    USE_LUA=1
    LUA_LIB_NAME=lua5.4
    USE_PCRE2=1
    USE_PCRE2_JIT=1
    USE_PROMEX=1
    USE_ZLIB=1
  )

  cat << EOF > "${PROFILE_DIR}/${STACK_NAME}.sh"
export PATH="/opt/drycc/${STACK_NAME}/sbin:\$PATH"
EOF

  install-packages libssl-dev libpcre2-dev liblua5.4-dev zlib1g-dev
  curl -fsSL -o haproxy.tar.gz "https://github.com/haproxy/haproxy/archive/refs/tags/v${STACK_VERSION}.tar.gz"
  tar -xzf haproxy.tar.gz
  cd "haproxy-${STACK_VERSION}"
  make -j "$(nproc)" "${make_options[@]}"
  make install "${make_options[@]}" PREFIX="${DATA_DIR}"
  "${DATA_DIR}/sbin/haproxy" -vv
  cd ..
  rm -rf haproxy.tar.gz "haproxy-${STACK_VERSION}"
}

# call build stack
build-stack "${1}"
