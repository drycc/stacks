#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  if [[ ${OS_ARCH} =~ "x86" ||  ${OS_ARCH} =~ "amd" ]]; then 
    OS_ARCH="x86_64"
<<<<<<< HEAD
    curl -sSL https://fastdl.mongodb.org/linux/mongodb-linux-${OS_ARCH}-debian12-${STACK_VERSION}.tgz | tar -xz
    mv ./mongodb-linux-${OS_ARCH}-debian12-${STACK_VERSION}/bin/* "${BIN_DIR}/"
    rm -rf ./mongodb-linux-${OS_ARCH}-debian12-${STACK_VERSION} 
  elif [[ ${OS_ARCH} =~ "arm" ]]; then
    OS_ARCH="aarch64"
    curl -sSl https://fastdl.mongodb.org/linux/mongodb-linux-${OS_ARCH}-ubuntu2204-${STACK_VERSION}.tgz | tar -xz
    mv ./mongodb-linux-${OS_ARCH}-ubuntu2204-${STACK_VERSION}/bin/* "${BIN_DIR}/"
    rm -rf ./mongodb-linux-${OS_ARCH}-ubuntu2204-${STACK_VERSION} 
=======
    curl -sSL https://fastdl.mongodb.org/linux/mongodb-linux-${OS_ARCH}-debian12-${STACK_VERSION}.tgz | tar -xvz
    mv ./mongodb-linux-${OS_ARCH}-debian12-${STACK_VERSION}/bin/* "${BIN_DIR}/"
    rm -rf ./mongodb-linux-${OS_ARCH}-debian12-${STACK_VERSION} 
  elif [[ ${OS_ARCH} =~ "arm" ]]; then
    install-packages python3-pip  python-dev-is-python3  python3-dev   python3-venv \
    build-essential git llvm libcurl4-openssl-dev libssl-dev libldap-dev libsasl2-dev  liblzma-dev libkrb5-dev
    python3 -m venv /usr/local/venv
    source /usr/local/venv/bin/activate
    curl -sSL https://fastdl.mongodb.org/src/mongodb-src-r${STACK_VERSION}.tar.gz | tar -xz
    cd mongodb-src-r${STACK_VERSION}
    python3 -m pip install -r etc/pip/compile-requirements.txt
    python3 -m pip install requirements_parser jsonschema memory_profiler puremagic networkx cxxfilt
    export GIT_PYTHON_REFRESH=quiet
    ./buildscripts/scons.py -j 2 --linker=gold --disable-warnings-as-errors install-core 
    cd build/install/bin
    strip mongos mongod
    mv * "${BIN_DIR}/"
    cd - && cd ../
    rm -rf mongodb-src-r${STACK_VERSION}
>>>>>>> 9f541ac348427b130a83d04347278c424a3821a6
  fi 
}
# call build stack
build-stack "${1}"
