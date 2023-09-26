#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  architecture=$(dpkg --print-architecture)
  curl -o "${BIN_DIR}"/yq \
    -L "https://github.com/mikefarah/yq/releases/download/v${STACK_VERSION}/yq_linux_$architecture"; \
  chmod +x "${BIN_DIR}"/yq
}

# call build stack
build-stack "${1}"
