#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path

  curl -sSL "https://github.com/quickwit-oss/quickwit/releases/download/v${STACK_VERSION}/quickwit-v${STACK_VERSION}-$(uname -m)-unknown-linux-gnu.tar.gz" | tar -xz
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"

  cp quickwit-v${STACK_VERSION}/quickwit "${BIN_DIR}"
  cp -rf quickwit-v${STACK_VERSION}/config "${DATA_DIR}"
  rm -rf quickwit-v${STACK_VERSION}

  # upx
  upx --lzma --best "${BIN_DIR}"/*
}

# call build stack
build-stack "${1}"
