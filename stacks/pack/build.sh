#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  if [[ "${OS_ARCH}" == "amd64" ]]; then
    pack_download_url="https://github.com/buildpacks/pack/releases/download/v${STACK_VERSION}/pack-v${STACK_VERSION}-linux.tgz"
  else
    pack_download_url="https://github.com/buildpacks/pack/releases/download/v${STACK_VERSION}/pack-v${STACK_VERSION}-linux-${OS_ARCH}.tgz"
  fi
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  curl -sSL "${pack_download_url}" | tar xvz -C "${BIN_DIR}"
}

# call build stack
build-stack "${1}"
