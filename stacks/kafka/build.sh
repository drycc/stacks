#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  curl -fsSL -o tmp.tar.gz https://dlcdn.apache.org/kafka/${STACK_VERSION}/kafka_2.13-${STACK_VERSION}.tgz
  tar -xzf tmp.tar.gz
  mv kafka_2.13-"${STACK_VERSION}"/* "${DATA_DIR}"
  rm -rf kafka_2.13-${STACK_VERSION} tmp.tar.gz
  cat  << EOF > ${PROFILE_DIR}/${STACK_NAME}.sh
export PATH="/opt/drycc/kafka/bin:\$PATH"
EOF
}

# call build stack
build-stack "${1}"

