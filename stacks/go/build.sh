#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  curl -L -o /opt/drycc/tmp.tar.gz https://go.dev/dl/go"${STACK_VERSION}".linux-"${OS_ARCH}".tar.gz
  cd /opt/drycc && tar -xzf tmp.tar.gz && rm -rf tmp.tar.gz && cd -
  cat  << EOF >> "${PROFILE_DIR}"/go.sh
export GOPATH=\$HOME/go
export PATH=\$PATH:\$GOPATH/bin
EOF
  cp -rf /opt/drycc/go/* ${DATA_DIR}
}

# call build stack
build-stack "${1}"
