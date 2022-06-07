#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  curl -fsSL -o tmp.tar.gz https://dlcdn.apache.org/zookeeper/zookeeper-${STACK_VERSION}/apache-zookeeper-${STACK_VERSION}-bin.tar.gz
  tar -xzf tmp.tar.gz
  cp -rf apache-zookeeper-${STACK_VERSION}-bin/* "${DATA_DIR}"
  rm -rf apache-zookeeper-${STACK_VERSION}-bin tmp.tar.gz
  cat  << EOF > ${PROFILE_DIR}/${STACK_NAME}.sh
export PATH="/opt/drycc/zookeeper/bin:\$PATH"
EOF
}

# call build stack
build-stack "${1}"
