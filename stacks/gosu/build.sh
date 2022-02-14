#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  BIN_DIR="${TARNAME}/data/common/bin"
  mkdir -p "${BIN_DIR}"
  curl -fsSL -o "${BIN_DIR}"/"${STACK_NAME}" https://github.com/tianon/gosu/releases/download/"${STACK_VERSION}"/"${STACK_NAME}"-"${OS_ARCH}"
  chmod +x "${BIN_DIR}"/"${STACK_NAME}"
}

# call build stack
build-stack "${1}"
