#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  install-packages \
  	cmake \

  # Generate binary
  curl -sSL "https://downloads.mariadb.org/interstitial/mariadb-${STACK_VERSION}/source/mariadb-${STACK_VERSION}.tar.gz" | tar -xz && \
  cd mariadb-"${STACK_VERSION}" && \
  pcre_version=$(< cmake/pcre.cmake grep 'ftp.pcre.org' |awk -F 'pcre2-' '{print $2}' | awk -F '.zip' '{print $1}')
  sed -i -e "s|http://ftp.pcre.org/pub/pcre|https://github.com/PhilipHazel/pcre2/releases/download/pcre2-${pcre_version}|g" cmake/pcre.cmake
  cmake . -DCMAKE_INSTALL_PREFIX=/opt/drycc/mariadb \
  -DMYSQL_DATADIR=/opt/drycc/mariadb/data \
  -DWITH_INNOBASE_STORAGE_ENGINE=1 \
  -DWITH_ARCHIVE_STORAGE_ENGINE=1 \
  -DWITH_BLACKHOLE_STORAGE_ENGINE=1 \
  -DWITH_READLINE=1 \
  -DWITH_SSL=system \
  -DWITH_ZLIB=system \
  -DWITH_LIBWRAP=0 \
  -DMYSQL_UNIX_ADDR=/tmp/mariadb.sock \
  -DDEFAULT_CHARSET=utf8 \
  -DDEFAULT_COLLATION=utf8_general_ci \
  && \
  make install

  mkdir -p "${PROFILE_DIR}"
  cat  << EOF > "${PROFILE_DIR}/${STACK_NAME}.sh"
export PATH="/opt/drycc/mariadb/bin:\$PATH"
EOF

  cp -rf /opt/drycc/mariadb/* "${DATA_DIR}"
}

# call build stack
build-stack "${1}"