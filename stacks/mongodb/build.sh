#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  if [[ ${STACK_VERSION} == [0-5].* ]]; then
    echo "mongodb: ${STACK_VERSION} is not supported on ${OS_FLAVOUR}; MongoDB 6.0 or newer is required" >&2
    return 1
  fi
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  if [[ ${OS_ARCH} =~ "x86" ||  ${OS_ARCH} =~ "amd" ]]; then 
    OS_ARCH="x86_64"
    OS_DISTRO="debian12"
    if [[ ${STACK_VERSION} == 6.* ]]; then
      OS_DISTRO="ubuntu2204"
    fi
    curl -sSL https://fastdl.mongodb.org/linux/mongodb-linux-${OS_ARCH}-${OS_DISTRO}-${STACK_VERSION}.tgz | tar -xz
    mv ./mongodb-linux-${OS_ARCH}-${OS_DISTRO}-${STACK_VERSION}/bin/* "${BIN_DIR}/"
    rm -rf ./mongodb-linux-${OS_ARCH}-${OS_DISTRO}-${STACK_VERSION}
  elif [[ ${OS_ARCH} =~ "arm" ]]; then
    OS_ARCH="aarch64"
    curl -sSl https://fastdl.mongodb.org/linux/mongodb-linux-${OS_ARCH}-ubuntu2204-${STACK_VERSION}.tgz | tar -xz
    mv ./mongodb-linux-${OS_ARCH}-ubuntu2204-${STACK_VERSION}/bin/* "${BIN_DIR}/"
    rm -rf ./mongodb-linux-${OS_ARCH}-ubuntu2204-${STACK_VERSION} 
  fi 
}
# call build stack
build-stack "${1}"