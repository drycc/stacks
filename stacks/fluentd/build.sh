#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  export STACK_DOWNLOAD_URL="http://47.75.184.187:8000" 
  cat  << EOF > ${PROFILE_DIR}/${STACK_NAME}.sh
export GEM_HOME=/opt/drycc/fluentd
export BUNDLE_SILENCE_ROOT_WARNING=1
export BUNDLE_APP_CONFIG="$GEM_HOME"
export PATH=$GEM_HOME/bin:$PATH
EOF
  . ${PROFILE_DIR}/${STACK_NAME}.sh
  ./make.sh
  echo "export LD_PRELOAD=/usr/lib/libjemalloc.so.2" >> ${PROFILE_DIR}/${STACK_NAME}.sh
  cp -rf /opt/drycc/fluentd/* "${DATA_DIR}"
}

# call build stack
build-stack "${1}"
