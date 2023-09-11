#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  VERSION=${STACK_VERSION}
  OS_BIT=$(getconf LONG_BIT)
  if [[ ${OS_ARCH} =~ "x86" ||  ${OS_ARCH} =~ "amd" ]]; then 
    OS_ARCH="x86"
  elif [[ ${OS_ARCH} =~ "arm" ]]; then
    OS_ARCH="arm"
  fi 

  URL=https://dev.mysql.com/get/Downloads/MySQL-Shell/mysql-shell-${VERSION}-linux-glibc2.28-${OS_ARCH}-${OS_BIT}bit.tar.gz
  # echo $URL
  curl -fsSL -o tmp.tar.gz $URL
  tar -xzf tmp.tar.gz
  mv mysql-shell-${VERSION}-linux-glibc2.28-${OS_ARCH}-${OS_BIT}bit/* ${DATA_DIR}/
  rm -rf  tmp.tar.gz 
  rm -rf  mysql-shell-${VERSION}-linux-glibc2.28-${OS_ARCH}-${OS_BIT}bit/
}

# call build stack
build-stack "${1}"