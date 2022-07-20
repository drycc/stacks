#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  #install-packages fuse
  install-stack go 1.18.4 && . init-stack
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  # geesefs
  curl -sSL "https://github.com/yandex-cloud/geesefs/archive/refs/tags/v${STACK_VERSION}.tar.gz" | tar -xz \
  && mv geesefs-${STACK_VERSION} $GOPATH/src/geesefs/ \
  && cd $GOPATH/src/geesefs \
  && export GO111MODULE=on \
  && CGO_ENABLED=0 go build \
    -a -ldflags '-extldflags "-static"' -o /bin/geesefs .
  mv /bin/geesefs "${BIN_DIR}"

   # upx
  upx --lzma --best "${BIN_DIR}"/*
}

# call build stack
build-stack "${1}"

