#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  cat  << EOF > ${PROFILE_DIR}/${STACK_NAME}.sh
export PATH="/opt/drycc/${STACK_NAME}/sbin:\$PATH"
EOF
  echo "procps" > ${META_DIR}/dependencies
  install-packages xz-utils
  curl -fsSL -o tmp.tar.xz https://github.com/rabbitmq/rabbitmq-server/releases/download/v${STACK_VERSION}/rabbitmq-server-generic-unix-${STACK_VERSION}.tar.xz
  xz -d tmp.tar.xz
  tar -xvf tmp.tar
  cp -rf rabbitmq_server-${STACK_VERSION}/* "${DATA_DIR}"
  cp "${DATA_DIR}"/plugins/rabbitmq_management-*/priv/www/cli/rabbitmqadmin "${TARNAME}"/data/sbin
  chmod +x "${DATA_DIR}"/sbin/rabbitmqadmin
  rm -rf tmp.tar rabbitmq_server-${STACK_VERSION}
}

# call build stack
build-stack "${1}"

