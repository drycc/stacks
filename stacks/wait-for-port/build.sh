#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  BIN_DIR="${TARNAME}/data/common/bin"
  mkdir -p "${BIN_DIR}"
  curl -fsSL -o tmp.tar.gz https://github.com/bitnami/wait-for-port/releases/download/v${STACK_VERSION}/"${STACK_NAME}"-linux-"${OS_ARCH}".tar.gz
  tar -xvzf tmp.tar.gz
  mv "${STACK_NAME}"-linux-"${OS_ARCH}" "${BIN_DIR}"/"${STACK_NAME}"
  chmod +x "${BIN_DIR}"/"${STACK_NAME}"
  rm -rf tmp.tar.gz
}

# call build stack
build-stack "${1}"
