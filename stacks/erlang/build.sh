#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  cat << EOF > "${TARNAME}"/meta/dependencies
libssl1.1
libodbc1
libsctp1
libwxgtk3.0
EOF
  export PATH="/opt/drycc/erlang/bin:$PATH"
  export C_INCLUDE_PATH="/opt/drycc/erlang/include"
  export CPLUS_INCLUDE_PATH="/opt/drycc/erlang/include"
  export LIBRARY_PATH="/opt/drycc/erlang/lib"
  export LD_LIBRARY_PATH="/opt/drycc/erlang/lib"
  export PKG_CONFIG_PATH="/opt/drycc/erlang/lib/pkg-config"
  ./make.sh
  cp -rf /opt/drycc/erlang /workspace/"${TARNAME}"/data
}

# call build stack
build-stack "${1}"