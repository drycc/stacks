#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  VERSION=${STACK_VERSION}

  curl -L -o nessie-quarkus-${STACK_VERSION}-runner.jar \
  https://github.com/projectnessie/nessie/releases/download/nessie-${STACK_VERSION}/nessie-quarkus-${STACK_VERSION}-runner.jar
  cp nessie-quarkus-${STACK_VERSION}-runner.jar "${DATA_DIR}"
}

# call build stack
build-stack "${1}"

