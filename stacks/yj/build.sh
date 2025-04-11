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
  curl -fsSL -o tmp.tar.gz https://github.com/sclevine/yj/archive/refs/tags/v${STACK_VERSION}.tar.gz
  tar -xvzf tmp.tar.gz
  cd yj-${STACK_VERSION}
  # fix CVE-2022-28948
  go get -u ./...; go mod tidy; go mod vendor

  go build -ldflags "-X main.Version=${STACK_VERSION}" -o "${BIN_DIR}"/yj
  cd ..
  rm -rf yj-${STACK_VERSION} tmp.tar.gz
}

# call build stack
build-stack "${1}"
