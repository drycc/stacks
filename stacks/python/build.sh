#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  cat << EOF > "${TARNAME}"/meta/dependencies
expat
libffi-dev
pkg-config
libsqlite3-dev
EOF
  export PATH="/opt/drycc/python/bin:$PATH"
  export C_INCLUDE_PATH="/opt/drycc/python/include"
  export CPLUS_INCLUDE_PATH="/opt/drycc/python/include"
  export LIBRARY_PATH="/opt/drycc/python/lib"
  export LD_LIBRARY_PATH="/opt/drycc/python/lib"
  export PKG_CONFIG_PATH="/opt/drycc/python/lib/pkg-config"
  ./make.sh
  cp -rf /opt/drycc/python /workspace/"${TARNAME}"/data
}

# call build stack
build-stack "${1}"