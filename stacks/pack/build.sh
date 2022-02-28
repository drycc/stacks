#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  install-packages make
  install-stack go 1.17.7 && . init-stack

  curl -sSL "https://github.com/buildpacks/pack/archive/refs/tags/v${STACK_VERSION}.tar.gz" | tar -xz \
  && cd pack-${STACK_VERSION} \
  && make

  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  mv ./out/pack "${BIN_DIR}"
  rm -rf pack-${STACK_VERSION}
}

# call build stack
build-stack "${1}"

