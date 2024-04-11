#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  if [[ ${OS_ARCH} =~ "x86" ||  ${OS_ARCH} =~ "amd" ]]; then 
    OS_ARCH="x86_64"
    curl -sSL https://fastdl.mongodb.org/linux/mongodb-linux-${OS_ARCH}-debian12-${STACK_VERSION}.tgz | tar -xz
    mv ./mongodb-linux-${OS_ARCH}-debian12-${STACK_VERSION}/bin/* "${BIN_DIR}/"
    rm -rf ./mongodb-linux-${OS_ARCH}-debian12-${STACK_VERSION} 
  elif [[ ${OS_ARCH} =~ "arm" ]]; then
    OS_ARCH="aarch64"
    curl -sSl https://fastdl.mongodb.org/linux/mongodb-linux-${OS_ARCH}-ubuntu2204-${STACK_VERSION}.tgz | tar -xz
    mv ./mongodb-linux-${OS_ARCH}-ubuntu2204-${STACK_VERSION}/bin/* "${BIN_DIR}/"
    rm -rf ./mongodb-linux-${OS_ARCH}-ubuntu2204-${STACK_VERSION} 
  fi 
}
# call build stack
build-stack "${1}"
