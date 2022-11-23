#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  install-packages \
    gcc liblzo2-dev make cmake git build-essential
  install-stack go 1.19.3
  . /opt/drycc/go/profile.d/*.sh

  git clone https://github.com/wal-g/wal-g/  $GOPATH/src/wal-g \
    && cd $GOPATH/src/wal-g/ \
    && git checkout v$STACK_VERSION \
    && make deps \
    && make pg_install

  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  mv /wal-g "${BIN_DIR}"
}

# call build stack
build-stack "${1}"

