#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

function install-deps() {
  install-packages build-essential \
        autoconf \
        libtool \
        git \
        ruby \
        bison \
        flex \
        python3 \
        python3-pip \
        wget && \
    pip3 install pipenv
}

# Implement build function
function build() {
  generate-stack-path
  install-deps
  rm -rf jq
  git clone --dept 1 -b jq-${STACK_VERSION} https://github.com/stedolan/jq
  cd jq
  git submodule update --init
  autoreconf -fi
  ./configure --with-oniguruma=builtin --enable-all-static --prefix=/opt/drycc/jq
  make LDFLAGS=-all-static
  make install
  cp -rf /opt/drycc/jq/* ${DATA_DIR}
  cd - && rm -rf jq
}

# call build stack
build-stack "${1}"
