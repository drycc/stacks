#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  # ref : https://github.com/dbeaver/cloudbeaver/wiki/Build-and-deploy
<<<<<<< HEAD
  # git tag --sorted=-creatordate --merged remotes/origin/release_23_2_5
  cd /opt/drycc/
  . init-stack
  JAVA_VERSION=17.0.9
  NODE_VERSION=16.20.1
  DBEAVER_VERSION=23.2.5 #CLOUD_VERSION 23.1.4
  install-stack java ${JAVA_VERSION}
  install-packages maven gnupg gnupg2 git
=======
  cd /opt/drycc/
  . init-stack
  NODE_VERSION=16.20.1
  DBEAVER_VERSION=23.2.5
  install-packages openjdk-17-jdk maven gnupg gnupg2 git
>>>>>>> a5bb8f1c00ad06e2e19aaba2b69d797d6da12229
  java --version &&  mvn --version 
  curl -sL https://dl.yarnpkg.com/debian/pubkey.gpg | apt-key add -
  echo "deb https://dl.yarnpkg.com/debian/ stable main" |  tee /etc/apt/sources.list.d/yarn.list
  curl -sL https://deb.nodesource.com/setup_14.x |   bash -
  install-packages yarn
  yarn --version
<<<<<<< HEAD
  install-stack node ${NODE_VERSION}
  export PATH=${PATH}:/opt/drycc/node/bin
  git clone https://github.com/dbeaver/dbeaver.git 
  cd dbeaver 
  git checkout $DBEAVER_VERSION
  cd ..
  git clone https://github.com/dbeaver/cloudbeaver.git 
  cd cloudbeaver 
  git checkout ${STACK_VERSION}
  cd deploy && ./build.sh && cp -r cloudbeaver ${DATA_DIR}
  
}
# call build stack
build-stack "${1}"
=======
  install-stack node $NODE_VERSION
  export PATH=$PATH:/opt/drycc/node/bin
  git clone https://github.com/dbeaver/dbeaver.git && cd dbeaver &&  git checkout $DBEAVER_VERSION
  cd ..
  git clone https://github.com/dbeaver/cloudbeaver.git && cd cloudbeaver/ && git checkout $STACK_VERSION
  cd deploy && sh build.sh && cp -r cloudbeaver ${DATA_DIR}
}
# call build stack
build-stack "${1}"
>>>>>>> a5bb8f1c00ad06e2e19aaba2b69d797d6da12229
