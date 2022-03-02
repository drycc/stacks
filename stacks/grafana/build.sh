#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  curl -fsSL -o tmp.tar.gz https://dl.grafana.com/oss/release/grafana-${STACK_VERSION}.linux-${OS_ARCH}.tar.gz
  tar -xzf tmp.tar.gz
  cp -rf grafana-${STACK_VERSION}/* ${DATA_DIR}
  rm -rf tmp.tar.gz grafana-${STACK_VERSION}
}

# call build stack
build-stack "${1}"
