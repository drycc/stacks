#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  ETC_DIR="${DATA_DIR}"/etc
  mkdir -p "${BIN_DIR}"
  mkdir -p "${ETC_DIR}"
  export LATEST_VERSION=${STACK_VERSION}

  case $(uname -m) in
    x86_64) ARCH=amd64 ;;
    aarch64) ARCH=arm64 ;;
    *) echo "Unknown architecture $(uname -m)"; exit 1 ;;
  esac

  for PKG in clickhouse-common-static clickhouse-server clickhouse-client clickhouse-keeper
  do
    curl -fO "https://packages.clickhouse.com/tgz/stable/$PKG-$LATEST_VERSION-${ARCH}.tgz" \
      || curl -fO "https://packages.clickhouse.com/tgz/stable/$PKG-$LATEST_VERSION.tgz"
  done

  tar -xzvf "clickhouse-common-static-$LATEST_VERSION-${ARCH}.tgz" \
    || tar -xzvf "clickhouse-common-static-$LATEST_VERSION.tgz"

  mv clickhouse-common-static-$LATEST_VERSION/usr/bin/* ${BIN_DIR}/
  ls -l ${BIN_DIR}/

  tar -xzvf "clickhouse-server-$LATEST_VERSION-${ARCH}.tgz" \
    || tar -xzvf "clickhouse-server-$LATEST_VERSION.tgz"

  mv clickhouse-server-$LATEST_VERSION/usr/bin/* ${BIN_DIR}/
  mv clickhouse-server-$LATEST_VERSION/etc/clickhouse-server/* ${ETC_DIR}/

  tar -xzvf "clickhouse-client-$LATEST_VERSION-${ARCH}.tgz" \
    || tar -xzvf "clickhouse-client-$LATEST_VERSION.tgz"

  mv clickhouse-client-$LATEST_VERSION/usr/bin/* ${BIN_DIR}/
  tar -xzvf "clickhouse-keeper-$LATEST_VERSION-${ARCH}.tgz" \
   || tar -xzvf "clickhouse-keeper-$LATEST_VERSION.tgz"
  mv clickhouse-keeper-$LATEST_VERSION/usr/bin/* ${BIN_DIR}/

  ls -l ${BIN_DIR}/
  ls -l /workspace/clickhouse-24.3.2.23-linux-amd64-debian-12/

  rm clickhouse-server* -rf
  rm clickhouse-common-static* -rf
  rm clickhouse-client* -rf
  rm clickhouse-keeper* -rf
}
# call build stack
build-stack "${1}"
