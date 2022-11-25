#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  curl -sSL https://github.com/prometheus/node_exporter/releases/download/v${STACK_VERSION}/node_exporter-${STACK_VERSION}.linux-${OS_ARCH}.tar.gz | tar -xvz
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  mv ./node_exporter-${STACK_VERSION}.linux-${OS_ARCH}/node_exporter "${BIN_DIR}"
  rm -rf ./node_exporter-${STACK_VERSION}.linux-${OS_ARCH}
  #upx
  upx --lzma --best "${BIN_DIR}"/*
}

# call build stack
build-stack "${1}"
