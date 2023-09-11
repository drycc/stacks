#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

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
    libsasl2-modules-gssapi-mit \
    libkrb5-dev \
    libsasl2-dev \
    libldap2-dev \
    bison \
    autoconf \
    automake \
    libtool

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
  strip  /opt/drycc/mysql/bin/comp_err
  strip  /opt/drycc/mysql/bin/ibd2sdi
  strip  /opt/drycc/mysql/bin/innochecksum
  strip  /opt/drycc/mysql/bin/lz4_decompress
  strip  /opt/drycc/mysql/bin/my_print_defaults
  strip  /opt/drycc/mysql/bin/myisam_ftdump
  strip  /opt/drycc/mysql/bin/myisamchk
  strip  /opt/drycc/mysql/bin/myisamlog
  strip  /opt/drycc/mysql/bin/myisampack
  strip  /opt/drycc/mysql/bin/mysql
  strip  /opt/drycc/mysql/bin/mysql_config_editor
  strip  /opt/drycc/mysql/bin/mysql_migrate_keyring
  strip  /opt/drycc/mysql/bin/mysql_secure_installation
  strip  /opt/drycc/mysql/bin/mysql_ssl_rsa_setup
  strip  /opt/drycc/mysql/bin/mysql_tzinfo_to_sql
  strip  /opt/drycc/mysql/bin/mysql_upgrade
  strip  /opt/drycc/mysql/bin/mysqladmin
  strip  /opt/drycc/mysql/bin/mysqlbinlog
  strip  /opt/drycc/mysql/bin/mysqlcheck
  strip  /opt/drycc/mysql/bin/mysqld
  strip  /opt/drycc/mysql/bin/mysqldump
  strip  /opt/drycc/mysql/bin/mysqlimport
  strip  /opt/drycc/mysql/bin/mysqlpump
  strip  /opt/drycc/mysql/bin/mysqlrouter
  strip  /opt/drycc/mysql/bin/mysqlrouter_keyring
  strip  /opt/drycc/mysql/bin/mysqlrouter_passwd
  strip  /opt/drycc/mysql/bin/mysqlrouter_plugin_info
  strip  /opt/drycc/mysql/bin/mysqlshow
  strip  /opt/drycc/mysql/bin/mysqlslap
  strip  /opt/drycc/mysql/bin/perror
  strip  /opt/drycc/mysql/bin/zlib_decompress

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
