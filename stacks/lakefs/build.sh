#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  if [[ ${OS_ARCH} =~ "x86" ||  ${OS_ARCH} =~ "amd" ]]; then 
    OS_ARCH="x86_64"
  elif [[ ${OS_ARCH} =~ "arm" ]]; then
    OS_ARCH="arm64"
  fi 

  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  curl -fsSL -o tmp.tar.gz https://github.com/treeverse/lakeFS/releases/download/v${STACK_VERSION}/lakeFS_${STACK_VERSION}_Linux_${OS_ARCH}.tar.gz
  tar -xzf tmp.tar.gz
  mv lakectl "${BIN_DIR}"/lakectl
  mv lakefs "${BIN_DIR}"/lakefs
  rm -rf tmp.tar.gz
  chmod +x "${BIN_DIR}/lakectl"
  chmod +x "${BIN_DIR}/lakefs"
}

# call build stack
build-stack "${1}"