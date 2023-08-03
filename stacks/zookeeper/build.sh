#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  curl -fsSL -o tmp.tar.gz https://dlcdn.apache.org/zookeeper/zookeeper-${STACK_VERSION}/apache-zookeeper-${STACK_VERSION}-bin.tar.gz
  tar -xzf tmp.tar.gz
  mv apache-zookeeper-"${STACK_VERSION}"-bin/* "${DATA_DIR}"
  rm apache-zookeeper-"${STACK_VERSION}"-bin tmp.tar.gz -rf

  cat  << EOF > ${PROFILE_DIR}/${STACK_NAME}.sh
export PATH="/opt/drycc/zookeeper/bin:\$PATH"
EOF
}

# call build stack
build-stack "${1}"

