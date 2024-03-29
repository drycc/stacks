#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  install-packages \
  	cmake \

  # Generate binary
  curl -sSL "https://archive.mariadb.org/mariadb-${STACK_VERSION}/source/mariadb-${STACK_VERSION}.tar.gz" | tar -xz && \
  echo "running building..."
  cd mariadb-"${STACK_VERSION}" && \
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
  make install/strip 2>&1 >/dev/null
  echo "build mariadb ok..."
  mkdir -p "${PROFILE_DIR}"
  cat  << EOF > "${PROFILE_DIR}/${STACK_NAME}.sh"
export PATH="/opt/drycc/mariadb/bin:\$PATH"
EOF
  echo "generate profile ok..."
  cp -rf /opt/drycc/mariadb/* "${DATA_DIR}"
}

# call build stack
build-stack "${1}"

