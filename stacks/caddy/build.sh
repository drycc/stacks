#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  curl -fsSL -o tmp.tar.gz https://github.com/caddyserver/caddy/releases/download/v${STACK_VERSION}/caddy_${STACK_VERSION}_linux_${OS_ARCH}.tar.gz
  tar -xzf tmp.tar.gz
  mv caddy "${BIN_DIR}"
  rm LICENSE README.md tmp.tar.gz
}

# call build stack
build-stack "${1}"
