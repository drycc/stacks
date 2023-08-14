#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  install-packages \
    gcc liblzo2-dev make cmake git build-essential
  install-stack go "${GO_VERSION}"
  . /opt/drycc/go/profile.d/*.sh

  git clone -b v$STACK_VERSION --depth 1 https://github.com/fluent/fluent-bit  $GOPATH/src/fluent-bit \
    && cd $GOPATH/src/fluent-bit/build \
    && apt update \
    && apt install -yq flex bison libyaml-dev libssl-dev libsasl2-dev \
    && cmake -DFLB_ALL=Yes -DCMAKE_INSTALL_PREFIX=/opt/drycc/fluent-bit ../ \
    && make \
    && make install
  cp -rf /opt/drycc/fluent-bit/* "${DATA_DIR}"
}

# call build stack
build-stack "${1}"

