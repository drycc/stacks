#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  version=$(echo ${STACK_VERSION} | awk -F "." '{print "RELEASE."$1"-"$2"-"$3"T"$4"-"$5"-"$6"Z"}')
  curl -fsSL -o "${BIN_DIR}"/"${STACK_NAME}" https://dl.min.io/client/mc/release/linux-${OS_ARCH}/archive/mc.${version}
  chmod +x "${BIN_DIR}"/"${STACK_NAME}"
}

# call build stack
build-stack "${1}"
