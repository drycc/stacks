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
  mkdir -p /opt/drycc/erlang/profile.d
  cat  << EOF > /opt/drycc/erlang/profile.d/erlang.sh
export PATH="/opt/drycc/erlang/bin:\$PATH"
EOF
  . /opt/drycc/erlang/profile.d/erlang.sh
  ./make.sh
  cp -rf /opt/drycc/erlang /workspace/"${TARNAME}"/data
}

# call build stack
build-stack "${1}"