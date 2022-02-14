#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  cat << EOF > "${TARNAME}"/meta/dependencies
python3
EOF

  install-packages xz-utils
  curl -fsSL -o tmp.tar.xz https://github.com/rabbitmq/rabbitmq-server/releases/download/v${STACK_VERSION}/rabbitmq-server-generic-unix-${STACK_VERSION}.tar.xz
  xz -d tmp.tar.xz
  tar -xvf tmp.tar
  mv rabbitmq_server-3.9.13 "${TARNAME}"/data/rabbitmq
  cp "${TARNAME}"/data/rabbitmq/plugins/rabbitmq_management-*/priv/www/cli/rabbitmqadmin "${TARNAME}"/data/rabbitmq/sbin
  chmod +x "${TARNAME}"/data/rabbitmq/sbin/rabbitmqadmin
  rm -rf tmp.tar
}

# call build stack
build-stack "${1}"


