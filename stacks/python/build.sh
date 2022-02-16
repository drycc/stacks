#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  cat << EOF > "${META_DIR}"/dependencies
expat
libffi-dev
pkg-config
libsqlite3-dev
EOF
  mkdir -p /opt/drycc/python/profile.d
  cat << EOF > /opt/drycc/python/profile.d/python.sh
  export PATH="/opt/drycc/python/bin:\$PATH"
  export C_INCLUDE_PATH="/opt/drycc/python/include:\$C_INCLUDE_PATH"
  export CPLUS_INCLUDE_PATH="/opt/drycc/python/include:\$CPLUS_INCLUDE_PATH"
  export LIBRARY_PATH="/opt/drycc/python/lib:\$LIBRARY_PATH"
  export LD_LIBRARY_PATH="/opt/drycc/python/lib:\$LD_LIBRARY_PATH"
  export PKG_CONFIG_PATH="/opt/drycc/python/lib/pkg-config:\$PKG_CONFIG_PATH"
EOF
  . /opt/drycc/python/profile.d/python.sh
  ./make.sh
  cp -rf /opt/drycc/python/* ${DATA_DIR}
}

# call build stack
build-stack "${1}"