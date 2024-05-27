#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  install-stack go "${GO_VERSION}" && . init-stack
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  git clone -b v${STACK_VERSION} --dept=1 https://github.com/RocksLabs/kvrocks_exporter.git
  cd kvrocks_exporter; go build main.go; mv main "${BIN_DIR}"/kvrocks_exporter; cd ..
  rm -rf kvrocks_exporter
  # upx
  upx --lzma --best "${BIN_DIR}"/*
}

# call build stack
build-stack "${1}"
