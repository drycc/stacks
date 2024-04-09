#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  case $(uname -m) in
    aarch64) target="envoy-${STACK_VERSION}-linux-aarch_64";;
    x86_64) target="envoy-${STACK_VERSION}-linux-x86_64";;
  esac

  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  curl -L -o "${BIN_DIR}"/envoy https://github.com/envoyproxy/envoy/releases/download/v${STACK_VERSION}/${target}
  chmod +x "${BIN_DIR}"/envoy
}

# call build stack
build-stack "${1}"
