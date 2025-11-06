#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"

  curl -fsSL -o rustfs.zip https://github.com/rustfs/rustfs/releases/download/${STACK_VERSION}/rustfs-linux-$(uname -m)-gnu-v${STACK_VERSION}.zip \
    && unzip -j rustfs.zip -d "${BIN_DIR}" \
    && rm rustfs.zip

  chmod +x "${BIN_DIR}"/"${STACK_NAME}"
}

# call build stack
build-stack "${1}"
