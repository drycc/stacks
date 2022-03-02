#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  ./make.sh
  mkdir -p "${DATA_DIR}"/env
  echo "/opt/drycc/java" > "${DATA_DIR}"/env/JAVA_HOME
  cat  << EOF >> ${PROFILE_DIR}/${STACK_NAME}.sh
export LD_LIBRARY_PATH="\${JAVA_HOME}/jre/lib/${OS_ARCH}/server:\${LD_LIBRARY_PATH}"
EOF

}

# call build stack
build-stack "${1}"
