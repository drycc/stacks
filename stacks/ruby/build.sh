#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  source-stack-path
  ./make.sh
  cp -rf /opt/drycc/ruby/* "${DATA_DIR}"
}

# call build stack
build-stack "${1}"
