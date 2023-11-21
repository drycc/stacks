#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils
# Implement build function
function build() {
  # Generate binary
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  # postgresql
  curl -fsSL -o pgweb_linux_${OS_ARCH}.zip  "https://github.com/sosedoff/pgweb/releases/download/${STACK_VERSION}/pgweb_linux_${OS_ARCH}.zip" 
  unzip pgweb_linux_${OS_ARCH}.zip
  rm pgweb_linux_${OS_ARCH}.zip 
  mv pgweb_linux_${OS_ARCH} "${BIN_DIR}"
}

# call build stack
build-stack "${1}"