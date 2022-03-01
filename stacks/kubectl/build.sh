#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  curl -fsSL -o "${BIN_DIR}/kubectl" "https://dl.k8s.io/v${STACK_VERSION}/bin/linux/${OS_ARCH}/kubectl"
  chmod +x "${BIN_DIR}/kubectl"
}

# call build stack
build-stack "${1}"

