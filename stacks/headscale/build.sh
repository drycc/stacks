#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  curl -fsSL "https://github.com/juanfont/headscale/releases/download/v${STACK_VERSION}/headscale_${STACK_VERSION}_linux_${OS_ARCH}" -o "${BIN_DIR}/${STACK_NAME}"
  chmod +x "${BIN_DIR}"/"${STACK_NAME}"
  # upx
  upx --lzma --best "${BIN_DIR}"/*
}

# call build stack
build-stack "${1}"
