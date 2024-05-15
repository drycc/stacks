#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  architecture=$(dpkg --print-architecture)
  package="etcd-v${STACK_VERSION}-linux-${architecture}"

  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  # build kvrocks
  curl -sSL https://github.com/apache/kvrocks/archive/refs/tags/v${STACK_VERSION}.tar.gz | tar xvz
  cd kvrocks-${STACK_VERSION}
  apt install -y git build-essential cmake libtool python3 libssl-dev
  ./x.py build; cd ..
  # build kvrocks controller
  install-stack go "${GO_VERSION}" && . init-stack
  KVROCKS_CONTROLLER_GIT_URL=https://github.com/apache/kvrocks-controller
  KVROCKS_CONTROLLER_VERSION=$(curl -Ls $KVROCKS_CONTROLLER_GIT_URL/tags|grep apache/kvrocks-controller/releases/tag/ | sed -E 's/.*\/apache\/kvrocks-controller\/releases\/tag\/v([0-9\.]{1,}(-rc.[0-9]{1,})?)".*/\1/g' | head -1)
  git clone --dept 1 -b v${KVROCKS_CONTROLLER_VERSION} https://github.com/apache/kvrocks-controller
  cd kvrocks-controller
  make; cd ..
  
  # cp kvrocks
  cp kvrocks-${STACK_VERSION}/build/{kvrocks,kvrocks2redis} $BIN_DIR
  # cp kvrocks controller
  cp kvrocks-controller/_build/* $BIN_DIR

  # clean
  rm -rf kvrocks-controller kvrocks-${STACK_VERSION}

  chmod +x "${BIN_DIR}"/*
  # upx
  upx --lzma --best "${BIN_DIR}"/*
}

# call build stack
build-stack "${1}"
