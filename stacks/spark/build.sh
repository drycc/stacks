#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  curl -fsSL -o tmp.tgz https://dlcdn.apache.org/spark/spark-${STACK_VERSION}/spark-${STACK_VERSION}-bin-hadoop3.tgz
  tar -xzf tmp.tgz
  mv spark-${STACK_VERSION}-bin-hadoop3/* "${DATA_DIR}"
  rm spark-${STACK_VERSION}-bin-hadoop3 tmp.tgz -rf

  mkdir -p "${DATA_DIR}"/env
  echo "/opt/drycc/spark" > "${DATA_DIR}"/env/SPARK_HOME
  cat  << EOF > ${PROFILE_DIR}/${STACK_NAME}.sh
export PATH="/opt/drycc/spark/bin:\$PATH"
export PATH="/opt/drycc/${STACK_NAME}/sbin:\$PATH"
EOF
}

# call build stack
build-stack "${1}"

