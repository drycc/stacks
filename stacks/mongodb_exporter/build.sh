#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  if [[ ${OS_ARCH} =~ "x86" ||  ${OS_ARCH} =~ "amd" ]]; then 
    OS_ARCH="amd64"
    curl -sSL  https://github.com/percona/mongodb_exporter/releases/download/v${STACK_VERSION}/mongodb_exporter-${STACK_VERSION}.linux-${OS_ARCH}.tar.gz  |tar -xz
    mv ./mongodb_exporter-${STACK_VERSION}.linux-${OS_ARCH}/mongodb_exporter "${BIN_DIR}/"
    rm -rf ./mongodb_exporter-${STACK_VERSION}.linux-${OS_ARCH}
  elif [[ ${OS_ARCH} =~ "arm" ]]; then
    OS_ARCH="arm64"
    curl -sSL  https://github.com/percona/mongodb_exporter/releases/download/v${STACK_VERSION}/mongodb_exporter-${STACK_VERSION}.linux-${OS_ARCH}.tar.gz  |tar -xz
    mv ./mongodb_exporter-${STACK_VERSION}.linux-${OS_ARCH}/mongodb_exporter "${BIN_DIR}/"
    rm -rf ./mongodb_exporter-${STACK_VERSION}.linux-${OS_ARCH}
  fi 
}
# call build stack
build-stack "${1}"