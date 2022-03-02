#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"

  # Install the infuxd server
  curl -fsSL -o tmp.tar.gz https://dl.influxdata.com/influxdb/releases/influxdb2-${STACK_VERSION}-linux-${OS_ARCH}.tar.gz
  tar -xzf tmp.tar.gz
  mv influxdb2-${STACK_VERSION}-linux-${OS_ARCH}/influxd "${BIN_DIR}"/influxd
  rm -rf tmp.tar.gz influxdb2-${STACK_VERSION}-linux-${OS_ARCH}

  # Install the influx CLI
  client_version=$(curl -Ls https://github.com/influxdata/influx-cli/releases|grep /influxdata/influx-cli/releases/tag/ | sed -E 's/.*\/influxdata\/influx-cli\/releases\/tag\/v([0-9\.]{1,}(-rc.[0-9]{1,})?)".*/\1/g' | head -1)
  curl -fsSL -o tmp.tar.gz https://dl.influxdata.com/influxdb/releases/influxdb2-client-${client_version}-linux-${OS_ARCH}.tar.gz
  tar -xzf tmp.tar.gz
  mv influxdb2-client-${client_version}-linux-${OS_ARCH}/influx "${BIN_DIR}"/influx
  rm -rf tmp.tar.gz influxdb2-client-${client_version}-linux-${OS_ARCH}
}

# call build stack
build-stack "${1}"

