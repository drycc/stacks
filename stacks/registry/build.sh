#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  BIN_DIR="${TARNAME}/data/registry/bin"
  mkdir -p "${BIN_DIR}"
  curl -fsSL -o tmp.tar.gz https://github.com/distribution/distribution/releases/download/v${STACK_VERSION}/registry_${STACK_VERSION}_linux_${OS_ARCH}.tar.gz
  tar -xvzf tmp.tar.gz
  mv registry "${BIN_DIR}"
  rm LICENSE README.md tmp.tar.gz
  mkdir "${TARNAME}"/data/registry/profile.d
  cat << EOF > "${TARNAME}"/data/registry/profile.d/registry.sh
  export PATH="/opt/drycc/registry/bin:\$PATH"
EOF

}

# call build stack
build-stack "${1}"
