#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  cat  << EOF > ${PROFILE_DIR}/${STACK_NAME}.sh
export PATH="/opt/drycc/${STACK_NAME}/sbin:\$PATH"
EOF
  ./make.sh
  cp -rf /opt/drycc/nginx/* ${DATA_DIR}
}

# call build stack
build-stack "${1}"