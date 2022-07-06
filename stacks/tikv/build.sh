#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  # tikv-server
  curl -fsSL -o tikv.tar.gz https://tiup-mirrors.pingcap.com/tikv-v${STACK_VERSION}-linux-${OS_ARCH}.tar.gz
  tar -xzf tikv.tar.gz
  mv tikv-server "${BIN_DIR}"
  
  # pd-server
  curl -fsSL -o pd.tar.gz https://tiup-mirrors.pingcap.com/pd-v${STACK_VERSION}-linux-${OS_ARCH}.tar.gz
  tar -xzf pd.tar.gz
  mv pd-server "${BIN_DIR}"

  # tikv-ctl pd-ctl
  curl -fsSL -o ctl.tar.gz https://tiup-mirrors.pingcap.com/ctl-v${STACK_VERSION}-linux-${OS_ARCH}.tar.gz
  tar -xzf ctl.tar.gz
  mv tikv-ctl pd-ctl "${BIN_DIR}"

  # pd-recover
  curl -fsSL -o pd-recover.tar.gz https://tiup-mirrors.pingcap.com/pd-recover-v${STACK_VERSION}-linux-${OS_ARCH}.tar.gz
  tar -xzf pd-recover.tar.gz
  mv pd-recover "${BIN_DIR}"

  rm tikv.tar.gz pd.tar.gz ctl.tar.gz pd-recover.tar.gz binlogctl cdc ctl etcdctl tidb-ctl tidb-lightning-ctl -rf
}

# call build stack
build-stack "${1}"
