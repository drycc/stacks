#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  BIN_DIR="${TARNAME}/data/telegraf/bin"
  mkdir -p "${BIN_DIR}"
  curl -fsSL -o tmp.tar.gz https://dl.influxdata.com/telegraf/releases/telegraf-${STACK_VERSION}_linux_${OS_ARCH}.tar.gz
  tar -xvzf tmp.tar.gz
  mv telegraf-${STACK_VERSION}/usr/bin/telegraf ${BIN_DIR}
  rm -rf telegraf-${STACK_VERSION} tmp.tar.gz
  cat << EOF > "${TARNAME}"/data/telegraf/profile.d/telegraf.sh
  export PATH="/opt/drycc/telegraf/bin:\$PATH"
EOF
}

# call build stack
build-stack "${1}"
