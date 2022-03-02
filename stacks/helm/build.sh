#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  curl -fsSL -o tmp.tar.gz https://get.helm.sh/helm-v${STACK_VERSION}-linux-${OS_ARCH}.tar.gz
  tar -xzf tmp.tar.gz
  mv linux-${OS_ARCH}/helm "${BIN_DIR}"
  rm -rf linux-${OS_ARCH} tmp.tar.gz
}

# call build stack
build-stack "${1}"

