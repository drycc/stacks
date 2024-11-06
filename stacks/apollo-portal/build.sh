#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  
  curl -fsSL -o tmp.zip https://github.com/apolloconfig/apollo/releases/download/v${STACK_VERSION}/apollo-portal-${STACK_VERSION}-github.zip
  unzip tmp.zip -d "${DATA_DIR}"
  rm tmp.zip -rf
}

# call build stack
build-stack "${1}"
