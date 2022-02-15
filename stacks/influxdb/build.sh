#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  BIN_DIR="${TARNAME}/data/influxdb/bin"
  mkdir -p "${BIN_DIR}"

  curl -fsSL -o tmp.tar.gz https://dl.influxdata.com/influxdb/releases/influxdb2-${STACK_VERSION}-linux-${OS_ARCH}.tar.gz
  tar -xvzf tmp.tar.gz
  mv influxdb2-${STACK_VERSION}-linux-${OS_ARCH}/influxd "${BIN_DIR}"/influxd
  rm -rf tmp.tar.gz influxdb2-${STACK_VERSION}-linux-${OS_ARCH}
  cat  << EOF > ${TARNAME}/data/influxdb/profile.d/influxdb.sh
export PATH="/opt/drycc/influxdb/bin:\$PATH"
EOF

}

# call build stack
build-stack "${1}"
