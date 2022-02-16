#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  curl -fsSL -o "${BIN_DIR}"/"${STACK_NAME}" https://dl.min.io/server/minio/release/linux-${OS_ARCH}/minio.${STACK_VERSION}
  chmod +x "${BIN_DIR}"/"${STACK_NAME}"
}

# call build stack
build-stack "${1}"
