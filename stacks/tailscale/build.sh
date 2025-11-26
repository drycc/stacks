#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  install-stack go "${GO_VERSION}"
  . init-stack
  git clone -b v${STACK_VERSION} --depth=1 https://github.com/tailscale/tailscale.git
  cd tailscale
  # fix CVE-2022-28948
  export VERSION_LONG=${STACK_VERSION}
  export VERSION_SHORT=${STACK_VERSION}
  ./build_dist.sh tailscale.com/cmd/tailscale
  ./build_dist.sh tailscale.com/cmd/tailscaled
  mv tailscale tailscaled "${BIN_DIR}"
  cd ..
  rm -rf tailscale
  # upx
  upx --lzma --best "${BIN_DIR}"/*
}

# call build stack
build-stack "${1}"
