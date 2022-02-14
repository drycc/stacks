#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  curl -fsSL -o tmp.tar.gz https://dl.grafana.com/oss/release/grafana-${STACK_VERSION}.linux-${OS_ARCH}.tar.gz
  tar -xvzf tmp.tar.gz
  mv grafana-${STACK_VERSION} ${TARNAME}/data/grafana
  rm tmp.tar.gz
}

# call build stack
build-stack "${1}"
