#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils
POSTGIS_VERSION=$(curl -Ls https://github.com/postgis/postgis/tags|grep /postgis/postgis/releases/tag/ | sed -E 's/.*\/postgis\/postgis\/releases\/tag\/([0-9\.]{1,}(-rc.[0-9]{1,})?)".*/\1/g' | head -1)
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
    protobuf-c-compiler

  # postgresql
  curl -sSL "https://ftp.postgresql.org/pub/source/v${PG_VER}/postgresql-${PG_VER}.tar.gz" | tar -xz && \
  cd postgresql-"${PG_VER}" && \
    ./configure \
    --prefix=/opt/drycc/postgresql/"${PG_MAJOR}" \
    --enable-integer-datetimes \
    --enable-thread-safety \
    --enable-tap-tests \
    --with-uuid=e2fs \
    --with-gnu-ld \
    --with-pgport=5432 \
    --with-system-tzdata=/usr/share/zoneinfo \
    --with-includes=/usr/local/include \
    --with-libraries=/usr/local/lib \
    --with-krb5 \
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
    make world && \
    make install-world

  # postgis
  curl -sSL "https://download.osgeo.org/postgis/source/postgis-${POSTGIS_VERSION}.tar.gz" | tar -xz && \
  cd postgis-"${POSTGIS_VERSION}" && \
    ./configure \
    --prefix="/opt/drycc/postgresql/${PG_MAJOR}/postgis/${POSTGIS_VERSION}" \
    --with-pgconfig=/opt/drycc/postgresql/"${PG_MAJOR}"/bin/pg_config \
    && \
    make && \
    make install

  cat  << EOF > "${PROFILE_DIR}/${STACK_NAME}.sh"
export PATH="/opt/drycc/postgresql/$PG_MAJOR/bin:\$PATH"
export LD_LIBRARY_PATH="/opt/drycc/postgresql/$PG_MAJOR/lib:\$LD_LIBRARY_PATH"
EOF
  cp -rf /opt/drycc/postgresql/* "${DATA_DIR}"
  cd /workspace && rm "postgresql-${PG_VER}" -rf
}

# call build stack
build-stack "${1}"

