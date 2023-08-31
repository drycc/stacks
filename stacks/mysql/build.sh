#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  
  MYSQL_VERSION=$STACK_VERSION
  MYSQL_MAJOR=$(echo "${MYSQL_VERSION}"|cut -d"." -f1-2)

  mkdir -p /opt/drycc/mysql-${MYSQL_MAJOR}/

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

  cmake  -DDOWNLOAD_BOOST=1 -DWITH_BOOST=/tmp/boost/ -DBUILD_CONFIG=mysql_release -DWITH_AUTHENTICATION_LDAP=1 -DCMAKE_INSTALL_PREFIX=/opt/drycc/mysql-${MYSQL_MAJOR} -DSYSCONFDIR=/opt/drycc/mysql-${MYSQL_MAJOR}/conf -DDEFAULT_SYSCONFDIR=/opt/drycc/mysql-${MYSQL_MAJOR}/conf -DFORCE_INSOURCE_BUILD=1
  make  --jobs=$numcpu
  make  install --jobs=$numcpu
  make  clean
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/comp_err
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/ibd2sdi
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/innochecksum
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/lz4_decompress
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/my_print_defaults
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/myisam_ftdump
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/myisamchk
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/myisamlog
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/myisampack
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/mysql
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/mysql_config_editor
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/mysql_migrate_keyring
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/mysql_secure_installation
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/mysql_ssl_rsa_setup
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/mysql_tzinfo_to_sql
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/mysql_upgrade
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/mysqladmin
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/mysqlbinlog
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/mysqlcheck
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/mysqld
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/mysqldump
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/mysqlimport
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/mysqlpump
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/mysqlrouter
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/mysqlrouter_keyring
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/mysqlrouter_passwd
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/mysqlrouter_plugin_info
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/mysqlshow
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/mysqlslap
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/perror
  strip  /opt/drycc/mysql-${MYSQL_MAJOR}/bin/zlib_decompress

  # copy mysql build files to data dir
  cp -r /opt/drycc/mysql-${MYSQL_MAJOR}/ ${DATA_DIR}/

  # clean tmp data
  cd .. && rm -rf mysql-${MYSQL_VERSION} mysql-${MYSQL_VERSION}.tar.gz 
}

# call build stack
build-stack "${1}"