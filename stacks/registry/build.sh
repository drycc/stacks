#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  install-stack go "${GO_VERSION}"
  . init-stack
  curl -fsSL -o tmp.tar.gz https://github.com/distribution/distribution/archive/refs/tags/v${STACK_VERSION}.tar.gz
  tar -xvzf tmp.tar.gz
  cd distribution-${STACK_VERSION}
  go build cmd/registry/main.go
  mv main "${BIN_DIR}"/registry
  cd ..
  rm -rf distribution-${STACK_VERSION} tmp.tar.gz
}

# call build stack
build-stack "${1}"
