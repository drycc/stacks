#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  # ref : https://github.com/dbeaver/cloudbeaver/wiki/Build-and-deploy
  cd /opt/drycc/
  . init-stack
  JAVA_VERSION=17.0.9
  NODE_VERSION=16.20.1
  install-packages gnupg gnupg2 git maven
  mvn --version 
  curl -sL https://dl.yarnpkg.com/debian/pubkey.gpg | apt-key add -
  echo "deb https://dl.yarnpkg.com/debian/ stable main" |  tee /etc/apt/sources.list.d/yarn.list
  curl -sL https://deb.nodesource.com/setup_14.x |   bash -
  install-packages yarn
  yarn --version
  install-stack node ${NODE_VERSION}
  export PATH=${PATH}:/opt/drycc/node/bin
  git clone https://github.com/dbeaver/dbeaver.git 
  cd dbeaver 
  git checkout -b release_${STACK_VERSION} --track origin/release_${STACK_VERSION}
  cd ..
  git clone https://github.com/dbeaver/cloudbeaver.git 
  cd cloudbeaver 
  git checkout -b release_${STACK_VERSION} --track origin/release_${STACK_VERSION}
  cd deploy && ./build.sh && cp -r cloudbeaver/* ${DATA_DIR}
  cat << EOF >> "${PROFILE_DIR}"/cloudbeaver.sh
export CLOUDBEAVER_HOME="/opt/drycc/cloudbeaver"
EOF

}
# call build stack
build-stack "${1}"
