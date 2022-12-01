#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  install-stack go 1.19.3
  . /opt/drycc/go/profile.d/*.sh

  git clone --dept 1 -b v${STACK_VERSION} https://github.com/jimmidyson/configmap-reload $GOPATH/src/configmap-reload \
    && cd $GOPATH/src/configmap-reload/ \
    && make

  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  mv out/configmap-reload "${BIN_DIR}"

  #upx
  upx --lzma --best "${BIN_DIR}"/*
}

# call build stack
build-stack "${1}"

