#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils
POSTGIS_VERSION=$(curl -Ls https://github.com/postgis/postgis/tags|grep /postgis/postgis/releases/tag/ | sed -E 's/.*\/postgis\/postgis\/releases\/tag\/([0-9\.]{1,}(-rc.[0-9]{1,})?)".*/\1/g' | head -1)
TIMESCALE_VERSION=$(curl -Ls https://github.com/timescale/timescaledb/releases|grep /timescale/timescaledb/releases/tag/ | sed -E 's/.*\/timescale\/timescaledb\/releases\/tag\/([0-9\.]{1,})".*/\1/g' | head -1)
PGVECTOR_VERSION=$(curl -Ls https://github.com/pgvector/pgvector/tags | grep '/pgvector/pgvector/archive/refs/tags/' | sed -E 's|.*/tags/v([0-9]+\.[0-9]+\.[0-9]+).*|\1|' | sort -Vr | head -1)
PG_REPACK_VERSION=$(curl -Ls https://github.com/reorg/pg_repack/tags | grep '/pg_repack/archive/refs/tags/' | sed -E 's|.*/tags/ver_([0-9]+\.[0-9]+\.[0-9]+).*|\1|' | sort -Vr | head -1)

# Implement build function
function build() {
  # Generate binary
  PG_VER=${STACK_VERSION}
  PG_MAJOR=$(echo "${STACK_VERSION}"|cut -d"." -f1)

  install-packages \
    clang \
    dirmngr \
    gnupg \
    libclang-dev \
    libicu-dev \
    libipc-run-perl \
    libkrb5-dev \
    libldap2-dev \
    liblz4-dev \
    libpam-dev \
    libperl-dev \
    libpython3-dev \
    libreadline-dev \
    libssl-dev \
    libxml2-dev \
    libxslt1-dev \
    llvm \
    llvm-dev \
    locales \
    python3-dev \
    tcl-dev \
    uuid-dev \
    pkg-config \
    libgdal-dev \
    libgeos-dev \
    libjson-c-dev \
    libproj-dev \
    libprotobuf-c-dev \
    protobuf-c-compiler \
    bison \
    flex 
  echo "-----------------start buid postpostgres-------------"
  # postgresql
  curl -sSL "https://ftp.postgresql.org/pub/source/v${PG_VER}/postgresql-${PG_VER}.tar.gz" | tar -xz && \
  cd postgresql-"${PG_VER}" && \
    ./configure \
    --prefix=/opt/drycc/postgresql/"${PG_MAJOR}" \
    --enable-integer-datetimes \
    --enable-tap-tests \
    --with-uuid=e2fs \
    --with-pgport=5432 \
    --with-system-tzdata=/usr/share/zoneinfo \
    --with-includes=/usr/local/include \
    --with-libraries=/usr/local/lib \
    --with-gssapi \
    --with-ldap \
    --with-pam \
    --with-tcl \
    --with-perl \
    --with-python \
    --with-openssl \
    --with-libxml \
    --with-libxslt \
    --with-icu \
    --with-llvm \
    --with-lz4 \
    && \
    # we can change from world to world-bin in newer releases
    make world-bin && \
    make install-world-bin
  cd - 
  # postgis
  echo "-----------------start buid postgis-------------"
  curl -sSL "https://download.osgeo.org/postgis/source/postgis-${POSTGIS_VERSION}.tar.gz" | tar -xz && \
  cd postgis-"${POSTGIS_VERSION}" && \
    ./configure --with-pgconfig=/opt/drycc/postgresql/"${PG_MAJOR}"/bin/pg_config \
    && \
  make && \
  make install && \
  cd - && \
  rm -rf postgis-"${POSTGIS_VERSION}"
  
  # # timescaledb
  echo "-----------------start buid timescaledb-------------"
  curl -sSL "https://github.com/timescale/timescaledb/archive/refs/tags/${TIMESCALE_VERSION}.tar.gz" | tar -xz &&
  cd timescaledb-"${TIMESCALE_VERSION}" && \
  cmake -DPG_CONFIG=/opt/drycc/postgresql/"${PG_MAJOR}"/bin/pg_config && \
  make && \
  make install && \
  cd - && \
  rm -rf timescaledb-"${TIMESCALE_VERSION}"

  # pgvector
  echo "-----------------start buid vector-------------"
  export PG_CONFIG=/opt/drycc/postgresql/"${PG_MAJOR}"/bin/pg_config
  curl -sSL https://codeload.github.com/pgvector/pgvector/tar.gz/refs/tags/v${PGVECTOR_VERSION} | tar -xz &&
  cd pgvector-${PGVECTOR_VERSION} && \
  make && \
  make install && \
  cd - && \
  rm -rf pgvector-${PGVECTOR_VERSION}


# pg_repack
  echo "-----------------start buid pg_repack-------------"
  export PG_CONFIG=/opt/drycc/postgresql/"${PG_MAJOR}"/bin/pg_config
  curl -sSL https://github.com/reorg/pg_repack/archive/refs/tags/ver_${PG_REPACK_VERSION}.tar.gz | tar -xz &&
  cd pg_repack-ver_${PG_REPACK_VERSION} && \
  make && \
  make install && \
  cd - && \
  rm -rf pg_repack-ver-${PG_REPACK_VERSION}

  cat  << EOF > "${PROFILE_DIR}/${STACK_NAME}.sh"
export PATH="/opt/drycc/postgresql/$PG_MAJOR/bin:\$PATH"
export LD_LIBRARY_PATH="/opt/drycc/postgresql/$PG_MAJOR/lib:\$LD_LIBRARY_PATH"
export PG_CONFIG=/opt/drycc/postgresql/"${PG_MAJOR}"/bin/pg_config
EOF
  cp -rf /opt/drycc/postgresql/* "${DATA_DIR}"
  cd /workspace && rm -rf "postgresql-${PG_VER}"
}

# call build stack
build-stack "${1}"
