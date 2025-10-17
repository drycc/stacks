#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  rclone_zipname="rclone-v${STACK_VERSION}-linux-${OS_ARCH}"
  curl -SsL https://github.com/rclone/rclone/releases/download/v${STACK_VERSION}/${rclone_zipname}.zip -o rclone.zip \
    && unzip -j rclone.zip ${rclone_zipname}/rclone -d "${BIN_DIR}"
  chmod +x "${BIN_DIR}"/"${STACK_NAME}"
}

# call build stack
build-stack "${1}"
