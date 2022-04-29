#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  curl -fsSL -o tmp.tar.gz https://github.com/prometheus/mysqld_exporter/releases/download/v${STACK_VERSION}/mysqld_exporter-${STACK_VERSION}.linux-${OS_ARCH}.tar.gz
  tar -xzf tmp.tar.gz
  mv mysqld_exporter-${STACK_VERSION}.linux-${OS_ARCH}/mysqld_exporter "${BIN_DIR}"
  rm -rf mysqld_exporter-${STACK_VERSION}.linux-${OS_ARCH} tmp.tar.gz
}

# call build stack
build-stack "${1}"
