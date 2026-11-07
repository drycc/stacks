#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  # ref : https://github.com/dbeaver/cloudbeaver/wiki/Build-and-deploy
  cd /opt/drycc/
  . init-stack
  NODE_VERSION=24.13.1
  YARN_VERSION=4.14.1
  install-packages git maven xz-utils
  mvn --version

  # Match the upstream frontend-build workflow for this release. Corepack
  # activates the Yarn 4 release declared by webapp/package.json.
  case "${OS_ARCH}" in
    amd64) NODE_ARCH=x64 ;;
    arm64) NODE_ARCH=arm64 ;;
    *) echo "error: unsupported architecture: ${OS_ARCH}" >&2; exit 1 ;;
  esac
  curl -fsSL -o node.tar.xz \
    "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz"
  mkdir -p .build-node
  tar -xJf node.tar.xz -C .build-node --strip-components=1
  export PATH="$(pwd)/.build-node/bin:${PATH}"
  corepack enable
  corepack prepare "yarn@${YARN_VERSION}" --activate
  yarn --version
  rm -f node.tar.xz

  # Tags name the exact requested release; upstream branch names use a
  # different separator scheme and a failed checkout leaves the build on devel.
  git clone --depth 1 --branch "${STACK_VERSION}" https://github.com/dbeaver/dbeaver-common.git
  git clone --depth 1 --branch "${STACK_VERSION}" https://github.com/dbeaver/dbeaver.git
  git clone --depth 1 --branch "${STACK_VERSION}" https://github.com/dbeaver/cloudbeaver.git
  cd cloudbeaver

  cd deploy
  ./build.sh
  cp -r cloudbeaver/* ${DATA_DIR}
  cat << EOF >> "${PROFILE_DIR}"/cloudbeaver.sh
export CLOUDBEAVER_HOME="/opt/drycc/cloudbeaver"
EOF

}
# call build stack
build-stack "${1}"
