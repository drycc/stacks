#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"

  # juicefs
  curl -fsSL -o tmp.tar.gz https://github.com/juicedata/juicefs/releases/download/v${STACK_VERSION}/juicefs-${STACK_VERSION}-linux-${OS_ARCH}.tar.gz
  tar -xzf tmp.tar.gz
  mv juicefs "${BIN_DIR}"/juicefs
  rm -rf tmp.tar.gz LICENSE README*.md

  # upx
  upx --lzma --best "${BIN_DIR}"/*
}

# call build stack
build-stack "${1}"

