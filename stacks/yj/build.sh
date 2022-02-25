#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  architecture=$(dpkg --print-architecture); \
  case "$architecture" in \
    amd64) yj_name=yj-linux ;; \
    *) yj_name=yj-linux=$architecture ;; \
  esac ; \
  curl -o "${BIN_DIR}"/yj \
    -L "https://github.com/sclevine/yj/releases/download/v${STACK_VERSION}/$yj_name"; \
  chmod +x "${BIN_DIR}"/yj
}

# call build stack
build-stack "${1}"
