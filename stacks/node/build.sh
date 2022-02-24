#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  case "$OS_ARCH" in
    'amd64')
        downloadUrl="https://nodejs.org/dist/v${STACK_VERSION}/node-v${STACK_VERSION}-linux-x64.tar.xz";
        ;;
    'arm64')
        downloadUrl="https://nodejs.org/dist/v${STACK_VERSION}/node-v${STACK_VERSION}-linux-arm64.tar.xz";
        ;;
    *) echo >&2 "error: unsupported architecture: '$arch'"; exit 1 ;;
  esac;
  curl -fsSL -o node.tar.xz "${downloadUrl}"
  tar -xJf node.tar.xz
  cp -rf node-v${STACK_VERSION}-linux-*/* "${DATA_DIR}"
  rm -rf node-v${STACK_VERSION}-linux-* node.tar.xz
}

# call build stack
build-stack "${1}"
