#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  BIN_DIR="${TARNAME}/data/common/bin"
  mkdir -p "${BIN_DIR}"
  curl -fsSL -o "${BIN_DIR}"/"${STACK_NAME}" https://dl.min.io/client/mc/release/linux-${OS_ARCH}/mc.${STACK_VERSION}
  chmod +x "${BIN_DIR}"/"${STACK_NAME}"
}

# call build stack
build-stack "${1}"
