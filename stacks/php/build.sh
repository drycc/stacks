#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  echo "libpcre3-dev" > ${META_DIR}/dependencies
  mkdir -p /opt/drycc/php/profile.d
  cat << EOF > /opt/drycc/php/profile.d/php.sh
export PATH="/opt/drycc/php/bin:/opt/drycc/php/sbin:\$PATH"
export PHP_PEAR_PHP_BIN="/opt/drycc/php/bin/php"
export PHP_PEAR_INSTALL_DIR="/opt/drycc/php/lib/php"
export C_INCLUDE_PATH="/opt/drycc/php/include:\$C_INCLUDE_PATH"
export CPLUS_INCLUDE_PATH="/opt/drycc/php/include:\$CPLUS_INCLUDE_PATH"
EOF
  . /opt/drycc/php/profile.d/php.sh
  ./make.sh
  pecl config-set php_dir "/opt/drycc/php"
  pecl config-set bin_dir "/opt/drycc/php/bin"
  pecl config-set ext_dir "/opt/drycc/php/ext"
  pecl config-set doc_dir "/opt/drycc/php/docs"
  php -r "copy('https://install.phpcomposer.com/installer', 'composer-setup.php');"
  php composer-setup.php --install-dir="/opt/drycc/php/bin/"
  mv /opt/drycc/php/bin/composer.phar /opt/drycc/php/bin/composer
  mkdir -p /opt/drycc/php/{config,ext,docs}
  cp -rf /opt/drycc/php/* ${DATA_DIR}
  rm -rf composer-setup.php
}

# call build stack
build-stack "${1}"