#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  install-stack go "${GO_VERSION}" && . init-stack

  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"

  # build weed
  curl -sSL "https://github.com/seaweedfs/seaweedfs/archive/refs/tags/${STACK_VERSION}.tar.gz" | tar -xz \
  && mv seaweedfs-${STACK_VERSION} $GOPATH/src/seaweedfs/ \
  && cd $GOPATH/src/seaweedfs/weed \
  && go install -tags "tikv"
  mv $GOPATH/bin/weed "${BIN_DIR}"
  cd -
  

  # seaweedfs-csi-driver
  # WEED_CSI_VERSION=$(curl -Ls https://github.com/seaweedfs/seaweedfs-csi-driver/releases|grep /seaweedfs/seaweedfs-csi-driver/releases/tag/ | sed -E 's/.*\/seaweedfs\/seaweedfs-csi-driver\/releases\/tag\/v([0-9\.]{1,}(-rc.[0-9]{1,})?)".*/\1/g' | head -1)
  WEED_CSI_VERSION=master
  if [[ "$WEED_CSI_VERSION" == "master" ]]; then
    WEED_CSI_URL="https://github.com/seaweedfs/seaweedfs-csi-driver/archive/refs/heads/${WEED_CSI_VERSION}.tar.gz"
  else
    WEED_CSI_URL="https://github.com/seaweedfs/seaweedfs-csi-driver/archive/refs/tags/v${WEED_CSI_VERSION}.tar.gz"
  fi
  curl -sSL "${WEED_CSI_URL}" | tar -xz \
  && mv seaweedfs-csi-driver-${WEED_CSI_VERSION} $GOPATH/src/seaweedfs-csi-driver/ \
  && cd $GOPATH/src/seaweedfs-csi-driver \
  && go build -o "${BIN_DIR}"/weed-csi ./cmd/seaweedfs-csi-driver/main.go

  # upx
  upx --lzma --best "${BIN_DIR}"/*
}

# call build stack
build-stack "${1}"