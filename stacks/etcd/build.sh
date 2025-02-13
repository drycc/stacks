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

  curl -sSL https://github.com/etcd-io/etcd/releases/download/v${STACK_VERSION}/${package}.tar.gz | tar xvz
  cp ${package}/etcd ${package}/etcdctl $BIN_DIR
  rm -rf ${package}
  chmod +x "${BIN_DIR}"/*
}

# call build stack
build-stack "${1}"
