#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  # Generate binary
  PG_VER=${STACK_VERSION}
  PG_MAJOR=$(echo "${STACK_VERSION}"|cut -d"." -f1)

  cat << EOF > /workspace/"${TARNAME}"/meta/dependencies
binutils \
gdal-bin \
libproj-dev
EOF

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
		pkg-config

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

  mkdir -p "${PROFILE_DIR}"
  cat  << EOF > "${PROFILE_DIR}/${STACK_NAME}.sh"
export PATH="/opt/drycc/postgresql/$PG_MAJOR/bin:\$PATH"
EOF

  cp -rf /opt/drycc/postgresql/* "${DATA_DIR}"
}

# call build stack
build-stack "${1}"