#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  # ref : https://github.com/dbeaver/cloudbeaver/wiki/Build-and-deploy
  cd /opt/drycc/
  . init-stack
  NODE_VERSION=16.20.1
  DBEAVER_VERSION=23.2.5
  install-packages openjdk-17-jdk maven gnupg gnupg2 git
  java --version &&  mvn --version 
  curl -sL https://dl.yarnpkg.com/debian/pubkey.gpg | apt-key add -
  echo "deb https://dl.yarnpkg.com/debian/ stable main" |  tee /etc/apt/sources.list.d/yarn.list
  curl -sL https://deb.nodesource.com/setup_14.x |   bash -
  install-packages yarn
  yarn --version
  install-stack node $NODE_VERSION
  export PATH=$PATH:/opt/drycc/node/bin
  git clone https://github.com/dbeaver/dbeaver.git && cd dbeaver &&  git checkout $DBEAVER_VERSION
  cd ..
  git clone https://github.com/dbeaver/cloudbeaver.git && cd cloudbeaver/ && git checkout $STACK_VERSION
  cd deploy && sh build.sh && cp -r cloudbeaver ${DATA_DIR}
}
# call build stack
build-stack "${1}"
