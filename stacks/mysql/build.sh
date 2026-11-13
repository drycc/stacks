#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Strip installed ELF programs; optional utilities vary by MySQL release.
function strip-mysql-binaries() {
  local bin_dir="${1:?bin dir is required}" binary
  for binary in "${bin_dir}"/*; do
    if [ -f "${binary}" ] && file --brief "${binary}" | grep -q '^ELF '; then
      strip "${binary}" || return
    fi
  done
}

# Implement build function
function build() {
  generate-stack-path
  
  MYSQL_VERSION=$STACK_VERSION
  MYSQL_MAJOR=$(echo "${MYSQL_VERSION}"|cut -d"." -f1-2)

  mkdir -p /opt/drycc/mysql

# computer cpu numbers
  numcpu=$(cat /proc/cpuinfo | grep processor | wc -l)
  if [ $numcpu -le 2 ]
  then
    numcpu=2
  fi 

  DEBIAN_FRONTEND="noninteractive" 

  ## install packages 
  install-packages \
    libaio-dev \
    libudev-dev \
    libsasl2-modules-gssapi-mit \
    libkrb5-dev \
    libsasl2-dev \
    libldap2-dev \
    bison \
    autoconf \
    automake \
    libtool \
    libtirpc-dev

  # curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin v0.40.0
  ## download mysql.tar
  curl https://cdn.mysql.com/Downloads/MySQL-${MYSQL_MAJOR}/mysql-${MYSQL_VERSION}.tar.gz --output mysql-${MYSQL_VERSION}.tar.gz
  ## untar mysql.tar
  tar --no-same-owner -xf mysql-${MYSQL_VERSION}.tar.gz
  cd mysql-${MYSQL_VERSION}

  cmake  -DDOWNLOAD_BOOST=1 -DWITH_BOOST=/tmp/boost/ -DBUILD_CONFIG=mysql_release -DWITH_AUTHENTICATION_LDAP=1 -DCMAKE_INSTALL_PREFIX=/opt/drycc/mysql -DSYSCONFDIR=/opt/drycc/mysql/conf -DDEFAULT_SYSCONFDIR=/opt/drycc/mysql/conf -DFORCE_INSOURCE_BUILD=1
  make  --jobs=$numcpu
  make  install --jobs=$numcpu
  make  clean
  strip-mysql-binaries /opt/drycc/mysql/bin

  # remove mysql test dir
  rm -rf /opt/drycc/mysql/mysql-test
  rm -rf /opt/drycc/mysql/mysql-8.0/mysql-test

  # copy mysql build files to data dir
  cp -r /opt/drycc/mysql/ ${DATA_DIR}/

  # clean tmp data
  cd .. && rm -rf mysql-${MYSQL_VERSION} mysql-${MYSQL_VERSION}.tar.gz 
}

# call build stack
build-stack "${1}"
