#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  install-stack go 1.18.3 && . init-stack

  curl -sSL "https://github.com/chrislusf/seaweedfs/archive/refs/tags/${STACK_VERSION}.tar.gz" | tar -xz \
  && mv seaweedfs-${STACK_VERSION} $GOPATH/src/seaweedfs/ \
  && cd $GOPATH/src/seaweedfs/weed \
  && go install -tags "tikv"

  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  mv $GOPATH/bin/weed "${BIN_DIR}"
}

# call build stack
build-stack "${1}"

