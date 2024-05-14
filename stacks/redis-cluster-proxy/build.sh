#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  curl -fsSL -o "${BIN_DIR}"/"${STACK_NAME}" https://github.com/drycc-addons/redis-cluster-proxy/releases/download/v"${STACK_VERSION}"/"${STACK_NAME}"-linux."${OS_ARCH}"
  chmod +x "${BIN_DIR}"/"${STACK_NAME}"
}

# call build stack
build-stack "${1}"
