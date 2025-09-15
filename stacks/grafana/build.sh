#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  install-stack jq 1.7.1 && . init-stack
  url=$(curl -s "https://grafana.com/api/grafana/versions/${STACK_VERSION}" | \
    jq -r ".packages[] | select(.os == \"linux\" and (.arch == \"${OS_ARCH}\") and (.url | endswith(\".tar.gz\"))) | .url")
  echo "Downloading Grafana..."
  curl -fSL -o tmp.tar.gz "$url"
  tar -xzf tmp.tar.gz
  cp -rf grafana-${STACK_VERSION}/* ${DATA_DIR}
  rm -rf tmp.tar.gz grafana-${STACK_VERSION}
}

# call build stack
build-stack "${1}"
