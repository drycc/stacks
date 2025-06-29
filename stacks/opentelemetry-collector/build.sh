#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  curl -sSL https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v${STACK_VERSION}/otelcol-contrib_${STACK_VERSION}_linux_${OS_ARCH}.tar.gz | tar -xvz

  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  mv otelcol-contrib "${BIN_DIR}"/otelcol
  rm  -rf README.md
  #upx
  upx --lzma --best "${BIN_DIR}"/*
}

# call build stack
build-stack "${1}"
