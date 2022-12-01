#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  curl -sSL https://github.com/prometheus/pushgateway/releases/download/v${STACK_VERSION}/pushgateway-${STACK_VERSION}.linux-${OS_ARCH}.tar.gz | tar -xvz

  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  mv ./pushgateway-${STACK_VERSION}.linux-${OS_ARCH}/pushgateway "${BIN_DIR}"
  rm  -rf ./pushgateway-${STACK_VERSION}.linux-${OS_ARCH}
  #upx
  upx --lzma --best "${BIN_DIR}"/*
}

# call build stack
build-stack "${1}"
