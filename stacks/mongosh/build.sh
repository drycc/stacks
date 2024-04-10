#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  if [[ ${OS_ARCH} =~ "x86" ||  ${OS_ARCH} =~ "amd" ]]; then 
    curl https://downloads.mongodb.com/compass/mongosh-${STACK_VERSION}-linux-x64.tgz| tar -xvz
    mv ./mongosh-${STACK_VERSION}-linux-x64/bin/* "${BIN_DIR}/"
    rm -rf ./mongosh-${STACK_VERSION}-linux-x64 
  elif [[ ${OS_ARCH} =~ "arm" ]]; then
   curl -sSL  https://downloads.mongodb.com/compass/mongosh-${STACK_VERSION}-linux-arm64.tgz | tar -xvz
   mv ./mongosh-${STACK_VERSION}-linux-arm64/bin/* "${BIN_DIR}/"
   rm -rf ./mongosh-${STACK_VERSION}-linux-arm64 
  fi 
}
# call build stack
build-stack "${1}"
