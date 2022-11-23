#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  install-stack go 1.19.3 && . init-stack

  curl -sSL "https://github.com/vouch/vouch-proxy/archive/refs/tags/v${STACK_VERSION}.tar.gz" | tar -xz \
  && mv vouch-proxy-${STACK_VERSION} $GOPATH/src/vouch-proxy/ \
  && cd $GOPATH/src/vouch-proxy \
  && ./do.sh goget \
  && ./do.sh gobuildstatic \
  && ./do.sh install

  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  mv $GOPATH/bin/vouch-proxy "${BIN_DIR}"
}

# call build stack
build-stack "${1}"

