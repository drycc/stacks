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
  # k8s-csi-s3
  curl -sSL "https://github.com/yandex-cloud/k8s-csi-s3/archive/refs/tags/v${STACK_VERSION}.tar.gz" | tar -xz \
  && mv k8s-csi-s3-${STACK_VERSION} $GOPATH/src/k8s-csi-s3/ \
  && cd $GOPATH/src/k8s-csi-s3 \
  && export GO111MODULE=on \
  && CGO_ENABLED=0 go build \
    -a -ldflags '-extldflags "-static"' -o /bin/s3driver ./cmd/s3driver
  mv /bin/s3driver "${BIN_DIR}"

  # geesefs
  GEESEFS_VERSION=$(curl -Ls https://github.com/yandex-cloud/geesefs/releases|grep /yandex-cloud/geesefs/releases/tag/ | sed -E 's/.*\/yandex-cloud\/geesefs\/releases\/tag\/v([0-9\.]{1,}(-rc.[0-9]{1,})?)".*/\1/g' | head -1)
  curl -sSL "https://github.com/yandex-cloud/geesefs/archive/refs/tags/v${GEESEFS_VERSION}.tar.gz" | tar -xz \
  && mv geesefs-${GEESEFS_VERSION} $GOPATH/src/geesefs/ \
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

