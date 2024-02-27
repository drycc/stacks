#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  install-stack go "${GO_VERSION}" && . init-stack

  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"

  mkdir -p $GOPATH/src
  # build weed
  curl -sSL "https://github.com/seaweedfs/seaweedfs/archive/refs/tags/${STACK_VERSION}.tar.gz" | tar -xz \
  && mv seaweedfs-${STACK_VERSION} $GOPATH/src/seaweedfs/ \
  && cd $GOPATH/src/seaweedfs/weed \
  && go install -tags "tikv"
  mv $GOPATH/bin/weed "${BIN_DIR}"
  cd -
  

  # seaweedfs-csi-driver
  WEED_CSI_GIT_URL=https://github.com/seaweedfs/seaweedfs-csi-driver
  WEED_CSI_VERSION=$(curl -Ls $WEED_CSI_GIT_URL/releases|grep /seaweedfs/seaweedfs-csi-driver/releases/tag/ | sed -E 's/.*\/seaweedfs\/seaweedfs-csi-driver\/releases\/tag\/v([0-9\.]{1,}(-rc.[0-9]{1,})?)".*/\1/g' | head -1)
  git clone --depth 1 -b v$WEED_CSI_VERSION $WEED_CSI_GIT_URL $GOPATH/src/seaweedfs-csi-driver \
  && cd $GOPATH/src/seaweedfs-csi-driver \
  && LDFLAGS="-s -w -X github.com/seaweedfs/seaweedfs-csi-driver/pkg/driver.gitCommit=$(git rev-parse --short HEAD)" \
  && LDFLAGS="$LDFLAGS -X github.com/seaweedfs/seaweedfs-csi-driver/pkg/driver.driverVersion=${WEED_CSI_VERSION}" \
  && LDFLAGS="$LDFLAGS -X github.com/seaweedfs/seaweedfs-csi-driver/pkg/driver.buildDate=$(date --iso-8601=seconds)" \
  && export LDFLAGS \
  && go mod tidy \
  && make build \
  && cp _output/seaweedfs-csi-driver "${BIN_DIR}"/weed-csi

  # upx
  upx --lzma --best "${BIN_DIR}"/*
}

# call build stack
build-stack "${1}"