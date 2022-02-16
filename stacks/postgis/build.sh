#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  # Generate binary
  POSTGIS_VER=${STACK_VERSION} # 3.1.4

  install-packages \
    libgdal-dev \
		libgeos-dev \
		libjson-c-dev \
		libmysqlclient-dev \
		libproj-dev \
		libprotobuf-c-dev \
		libxml2-dev \
		protobuf-c-compiler

  curl -sSL "https://download.osgeo.org/postgis/source/postgis-"${POSTGIS_VER}".tar.gz" | tar -xz && \
	cd postgis-"${POSTGIS_VER}" && \
	./configure \
	--prefix=/opt/drycc/postgis/"${POSTGIS_VER}" \
	--with-pgconfig=/opt/drycc/postgresql/"${PG_MAJOR}"/bin/pg_config \
	&& \
	make && \
	make install

  cp -rf /opt/drycc/postgresql "${DATA_DIR}"
}

# call build stack
build-stack "${1}"
