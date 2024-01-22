#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  curl -fsSL -o tmp.tgz https://dlcdn.apache.org/flink/flink-${STACK_VERSION}/flink-${STACK_VERSION}-bin-scala_2.12.tgz
  tar -xzf tmp.tgz
  mv flink-${STACK_VERSION}/* "${DATA_DIR}"
  rm flink-${STACK_VERSION} tmp.tgz -rf

  mkdir -p "${DATA_DIR}"/env
  echo "/opt/drycc/flink" > "${DATA_DIR}"/env/FLINK_HOME
  cat  << EOF > ${PROFILE_DIR}/${STACK_NAME}.sh
export PATH="/opt/drycc/flink/bin:\$PATH"
EOF
}

# call build stack
build-stack "${1}"

