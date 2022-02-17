#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  mkdir -p /opt/drycc/php/profile.d
  cat << EOF > /opt/drycc/php/profile.d/php.sh
export PATH=/opt/drycc/php/bin:/opt/drycc/php/sbin:$PATH
export PHP_PEAR_PHP_BIN=/opt/drycc/php/bin/php
export PHP_PEAR_INSTALL_DIR=/opt/drycc/php/lib/php
EOF
  . /opt/drycc/php/profile.d/php.sh
  ./make.sh
  cp -rf /opt/drycc/php/* ${DATA_DIR}
}

# call build stack
build-stack "${1}"