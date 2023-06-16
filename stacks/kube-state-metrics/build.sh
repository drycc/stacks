#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  install-packages make
  install-stack go "${GO_VERSION}" && . init-stack

  curl -sSL "https://github.com/kubernetes/kube-state-metrics/archive/refs/tags/v${STACK_VERSION}.tar.gz" | tar -xz \
  && cd kube-state-metrics-${STACK_VERSION} \
  && make build-local

  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  mv ./kube-state-metrics "${BIN_DIR}"
  cd .. && rm -rf kube-state-metrics-${STACK_VERSION}
  #upx
  upx --lzma --best "${BIN_DIR}"/*
}

# call build stack
build-stack "${1}"
