#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  install-packages gcc liblzo2-dev git build-essential
  install-stack go "${GO_VERSION}"
  . init-stack
  
  echo $GOPATH
  git clone https://github.com/EamonZhang/airflow_exporter.git  $GOPATH/src/airflow_exporter 
  cd $GOPATH/src/airflow_exporter/
  go get
  go build -o airflow_exporter .

  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  mv airflow_exporter "${BIN_DIR}"
}

# call build stack
build-stack "${1}"

