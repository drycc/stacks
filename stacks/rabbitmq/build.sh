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
  RABBITMQADMIN_PATH=""
  for candidate in "${DATA_DIR}"/plugins/rabbitmq_management-*/priv/www/cli/rabbitmqadmin; do
    if [ -f "${candidate}" ]; then
      RABBITMQADMIN_PATH="${candidate}"
      break
    fi
  done
  if [ -n "${RABBITMQADMIN_PATH}" ]; then
    cp "${RABBITMQADMIN_PATH}" "${DATA_DIR}"/sbin
  else
    case "${OS_ARCH}" in
      amd64 | x86_64) RABBITMQADMIN_ARCH="x86_64" ;;
      arm64 | aarch64) RABBITMQADMIN_ARCH="aarch64" ;;
      *)
        echo "rabbitmq: unsupported rabbitmqadmin architecture ${OS_ARCH}" >&2
        return 1
        ;;
    esac
    RABBITMQADMIN_VERSION="${RABBITMQADMIN_VERSION:-2.30.0}"
    curl -fsSL -o "${DATA_DIR}"/sbin/rabbitmqadmin \
      "https://github.com/rabbitmq/rabbitmqadmin-ng/releases/download/v${RABBITMQADMIN_VERSION}/rabbitmqadmin-${RABBITMQADMIN_VERSION}-${RABBITMQADMIN_ARCH}-unknown-linux-gnu"
  fi
  chmod +x "${DATA_DIR}"/sbin/rabbitmqadmin
  rm -rf tmp.tar rabbitmq_server-${STACK_VERSION}
}

# call build stack
build-stack "${1}"

