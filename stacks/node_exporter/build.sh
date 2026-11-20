#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  for NODE_EXPORTER_ATTEMPT in 1 2 3; do
    if curl -fsSL --retry 6 --retry-all-errors --retry-delay 2 --retry-max-time 120 \
      -o node_exporter.tar.gz \
      "https://github.com/prometheus/node_exporter/releases/download/v${STACK_VERSION}/node_exporter-${STACK_VERSION}.linux-${OS_ARCH}.tar.gz" \
      && gzip -t node_exporter.tar.gz; then
      break
    fi
    rm -f node_exporter.tar.gz
    if [ "${NODE_EXPORTER_ATTEMPT}" -eq 3 ]; then
      echo "node_exporter: failed to download a valid archive after 3 attempts" >&2
      return 1
    fi
    sleep 2
  done
  tar -xzf node_exporter.tar.gz
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  mv ./node_exporter-${STACK_VERSION}.linux-${OS_ARCH}/node_exporter "${BIN_DIR}"
  rm -rf ./node_exporter-${STACK_VERSION}.linux-${OS_ARCH} node_exporter.tar.gz
  #upx
  upx --lzma --best "${BIN_DIR}"/*
}

# call build stack
build-stack "${1}"
