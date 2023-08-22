#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  install-packages \
    gcc liblzo2-dev make cmake git build-essential

  curl -fsSL -o tmp.tar.bz2 http://sourceforge.net/projects/netcat/files/netcat/${STACK_VERSION}/netcat-${STACK_VERSION}.tar.bz2
  tar -jxvf tmp.tar.bz2
  cd netcat-${STACK_VERSION}
  ./configure \
  --prefix=/opt/drycc/nc 

  make && make install
  cp -rf /opt/drycc/nc/* "${DATA_DIR}"
  cd .. && rm -rf netcat-${STACK_VERSION} tmp.tar.bz2
}

# call build stack
build-stack "${1}"

