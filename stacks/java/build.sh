#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  case $(uname -m) in
    aarch64) url="https://aka.ms/download-jdk/microsoft-jdk-${STACK_VERSION}-linux-aarch64.tar.gz";;
    x86_64) url="https://aka.ms/download-jdk/microsoft-jdk-${STACK_VERSION}-linux-x64.tar.gz";;
  esac
  curl -sSL "${url}" | tar -xz
  cp -rf jdk-${STACK_VERSION}*/* "${DATA_DIR}" && rm -rf jdk-${STACK_VERSION}*
  mkdir -p "${DATA_DIR}"/env
  echo "/opt/drycc/java" > "${DATA_DIR}"/env/JAVA_HOME
  cat  << EOF >> ${PROFILE_DIR}/${STACK_NAME}.sh
export LD_LIBRARY_PATH="\${JAVA_HOME}/lib/server:\${LD_LIBRARY_PATH}"
EOF

}

# call build stack
build-stack "${1}"
