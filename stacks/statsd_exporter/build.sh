#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  curl -fsSL -o tmp.tar.gz https://github.com/prometheus/statsd_exporter/releases/download/v${STACK_VERSION}/"${STACK_NAME}-${STACK_VERSION}.linux-${OS_ARCH}".tar.gz
  tar -xzf tmp.tar.gz
  mv "${STACK_NAME}-${STACK_VERSION}.linux-${OS_ARCH}"/"${STACK_NAME}" "${BIN_DIR}"/"${STACK_NAME}"
  chmod +x "${BIN_DIR}"/"${STACK_NAME}"
  rm -rf tmp.tar.gz "${STACK_NAME}-${STACK_VERSION}.linux-${OS_ARCH}"
}

# call build stack
build-stack "${1}"
