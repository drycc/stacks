#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  install-stack go "${GO_VERSION}" && . init-stack
  mkdir -p $GOPATH/src

  curl -sSL "https://github.com/subfuzion/envtpl/archive/refs/tags/v${STACK_VERSION}.tar.gz" | tar -xz \
  && mv envtpl-${STACK_VERSION} $GOPATH/src/envtpl/ \
  && cd $GOPATH/src/envtpl
  # fix CVE-2022-28948
  go get -u ./...; go mod tidy; go mod vendor

  export GO111MODULE=on
  CGO_ENABLED=0 go build \
    -ldflags "-X main.AppVersionMetadata=$(date -u +%s)" \
    -a -installsuffix cgo -o /bin/envtpl ./cmd/envtpl/.

  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  mv /bin/envtpl "${BIN_DIR}"
}

# call build stack
build-stack "${1}"

