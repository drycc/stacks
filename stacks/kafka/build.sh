#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  curl -fsSL -o tmp.tar.gz https://github.com/apache/kafka/archive/refs/tags/${STACK_VERSION}.tar.gz
  tar -xzf tmp.tar.gz
  mv kafka-"${STACK_VERSION}"/* "${DATA_DIR}"
  rm kafka-"${STACK_VERSION}" tmp.tar.gz -rf

  cat  << EOF > ${PROFILE_DIR}/${STACK_NAME}.sh
export PATH="/opt/drycc/kafka:/opt/drycc/kafka/bin:\$PATH"
EOF
}

# call build stack
build-stack "${1}"
