#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  curl -fsSL -o tmp.tar.gz https://dl.influxdata.com/telegraf/releases/telegraf-${STACK_VERSION}_linux_${OS_ARCH}.tar.gz
  tar -xzf tmp.tar.gz
  mv telegraf-${STACK_VERSION}/usr/bin/telegraf ${BIN_DIR}
  rm -rf telegraf-${STACK_VERSION} tmp.tar.gz
}

# call build stack
build-stack "${1}"
