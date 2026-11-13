#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  install-stack go "${GO_VERSION}" && . init-stack
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  git clone --depth 1 --branch "v${STACK_VERSION}" https://github.com/percona/mongodb_exporter.git
  cd mongodb_exporter
  make build COMPONENT_VERSION="v${STACK_VERSION}"
  mv mongodb_exporter "${BIN_DIR}/mongodb_exporter"
  cd ..
  rm -rf mongodb_exporter
}
# call build stack
build-stack "${1}"