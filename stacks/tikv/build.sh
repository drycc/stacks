#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  curl -fsSL -o tikv.tar.gz https://tiup-mirrors.pingcap.com/tikv-v${STACK_VERSION}-linux-${OS_ARCH}.tar.gz
  tar -xzf tikv.tar.gz
  mv tikv-server "${BIN_DIR}"
  curl -fsSL -o pd.tar.gz https://tiup-mirrors.pingcap.com/pd-v${STACK_VERSION}-linux-${OS_ARCH}.tar.gz
  tar -xzf pd.tar.gz
  mv pd-server "${BIN_DIR}"
  rm tikv.tar.gz pd.tar.gz
}

# call build stack
build-stack "${1}"
