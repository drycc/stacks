#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  case "$OS_ARCH" in 
    'amd64') 
        downloadUrl="https://artifacts.opensearch.org/releases/bundle/opensearch-dashboards/${STACK_VERSION}/opensearch-dashboards-${STACK_VERSION}-linux-x64.tar.gz";
        ;; 
    'arm64') 
        downloadUrl="https://artifacts.opensearch.org/releases/bundle/opensearch-dashboards/${STACK_VERSION}/opensearch-dashboards-${STACK_VERSION}-linux-arm64.tar.gz";
        ;; 
    *) echo >&2 "error: unsupported architecture: '$arch'"; exit 1 ;; 
  esac; 
  curl -fsSL -o tmp.tar.gz "${downloadUrl}"
  tar -xzf tmp.tar.gz
  mv opensearch-dashboards-${STACK_VERSION}/* "${DATA_DIR}"
  rm opensearch-dashboards-${STACK_VERSION} tmp.tar.gz -rf

  cat  << EOF > ${PROFILE_DIR}/${STACK_NAME}.sh
export PATH="/opt/drycc/${STACK_NAME}/bin:\$PATH"
EOF
}

# call build stack
build-stack "${1}"

