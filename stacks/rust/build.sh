#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  case "$OS_ARCH" in
    'amd64')
        downloadUrl="https://static.rust-lang.org/dist/rust-${STACK_VERSION}-x86_64-unknown-linux-gnu.tar.gz";
        ;;
    'arm64')
        downloadUrl="https://static.rust-lang.org/dist/rust-${STACK_VERSION}-aarch64-unknown-linux-gnu.tar.gz";
        ;;
    *) echo >&2 "error: unsupported architecture: '$arch'"; exit 1 ;;
  esac;
  curl -fsSL -o rust.tar.gz "${downloadUrl}"
  tar -xzf rust.tar.gz
  cd rust-${STACK_VERSION}-*-unknown-linux-gnu
  ./install.sh --prefix=/opt/drycc/rust
  rm -rf /opt/drycc/rust/share /opt/drycc/rust/bin/rustdoc
  cp -rf /opt/drycc/rust/* "${DATA_DIR}"
  mkdir -p "${DATA_DIR}"/target "${DATA_DIR}"/env
  echo "/opt/drycc/rust" > "${DATA_DIR}"/env/CARGO_HOME
  echo "/opt/drycc/rust/target" > "${DATA_DIR}"/env/CARGO_TARGET_DIR
  cd ..
  
  rm -rf rust-${STACK_VERSION}-*-unknown-linux-gnu rust.tar.gz
}

# call build stack
build-stack "${1}"
