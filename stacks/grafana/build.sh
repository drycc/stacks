#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  curl -fsSL -o tmp.tar.gz https://dl.grafana.com/oss/release/grafana-${STACK_VERSION}.linux-${OS_ARCH}.tar.gz
  tar -xvzf tmp.tar.gz
  mv grafana-${STACK_VERSION} ${TARNAME}/data/grafana
  rm tmp.tar.gz
  mkdir ${TARNAME}/data/grafana/profile.d
  cat  << EOF > ${TARNAME}/data/grafana/profile.d/grafana.sh
export PATH="/opt/drycc/grafana/bin:\$PATH"
EOF
}

# call build stack
build-stack "${1}"
