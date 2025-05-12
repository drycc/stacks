#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path

  mkdir -p tmp
  curl -sSL https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/v${STACK_VERSION}/vmutils-linux-${OS_ARCH}-v${STACK_VERSION}.tar.gz | tar -xvz -C tmp
  curl -sSL https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/v${STACK_VERSION}/victoria-metrics-linux-${OS_ARCH}-v${STACK_VERSION}-cluster.tar.gz | tar -xvz -C tmp
  
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"

  mv ./tmp/vmauth-prod "${BIN_DIR}"/vmauth
  mv ./tmp/vmalert-prod "${BIN_DIR}"/vmalert
  mv ./tmp/vmalert-tool-prod "${BIN_DIR}"/vmalert-tool
  mv ./tmp/vmagent-prod "${BIN_DIR}"/vmagent
  mv ./tmp/vmctl-prod "${BIN_DIR}"/vmctl
  mv ./tmp/vminsert-prod "${BIN_DIR}"/vminsert
  mv ./tmp/vmselect-prod "${BIN_DIR}"/vmselect
  mv ./tmp/vmstorage-prod "${BIN_DIR}"/vmstorage
  rm  -rf ./tmp
  #upx
  upx --lzma --best "${BIN_DIR}"/*
}

# call build stack
build-stack "${1}"

