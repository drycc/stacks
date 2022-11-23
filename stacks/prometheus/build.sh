#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  curl -sSL https://github.com/prometheus/prometheus/releases/download/v${STACK_VERSION}/prometheus-${STACK_VERSION}.linux-${OS_ARCH}.tar.gz | tar -xvz

  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  mv ./prometheus-${STACK_VERSION}.linux-${OS_ARCH}/promtool "${BIN_DIR}"
  mv ./prometheus-${STACK_VERSION}.linux-${OS_ARCH}/prometheus "${BIN_DIR}"
  rm  -rf ./prometheus-${STACK_VERSION}.linux-${OS_ARCH}
  #upx
  upx --lzma --best "${BIN_DIR}"/*
}

# call build stack
build-stack "${1}"

