#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  # Generate binary
  VALKEY_DOWNLOAD_URL="https://github.com/valkey-io/valkey/archive/refs/tags/${STACK_VERSION}.tar.gz"
  savedAptMark="$(apt-mark showmanual)"; \
  curl -fsSL -o valkey.tar.gz "$VALKEY_DOWNLOAD_URL"; \
  mkdir -p /usr/src/valkey; \
  tar -xzf valkey.tar.gz -C /usr/src/valkey --strip-components=1; \
  rm valkey.tar.gz; \
  grep -E '^ *createBoolConfig[(]"protected-mode",.*, *1 *,.*[)],$' /usr/src/valkey/src/config.c; \
  sed -ri 's!^( *createBoolConfig[(]"protected-mode",.*, *)1( *,.*[)],)$!\10\2!' /usr/src/valkey/src/config.c; \
  grep -E '^ *createBoolConfig[(]"protected-mode",.*, *0 *,.*[)],$' /usr/src/valkey/src/config.c; \
  gnuArch="$(dpkg-architecture --query DEB_BUILD_GNU_TYPE)"; \
  extraJemallocConfigureFlags="--build=$gnuArch"; \
  # https://salsa.debian.org/debian/jemalloc/-/blob/c0a88c37a551be7d12e4863435365c9a6a51525f/debian/rules#L8-23
  dpkgArch="$(dpkg --print-architecture)"; \
  case "${dpkgArch##*-}" in \
    amd64 | i386 | x32) extraJemallocConfigureFlags="$extraJemallocConfigureFlags --with-lg-page=12" ;; \
    *) extraJemallocConfigureFlags="$extraJemallocConfigureFlags --with-lg-page=16" ;; \
  esac; \
  extraJemallocConfigureFlags="$extraJemallocConfigureFlags --with-lg-hugepage=21"; \
  grep -F 'cd jemalloc && ./configure ' /usr/src/valkey/deps/Makefile; \
  sed -ri 's!cd jemalloc && ./configure !&'"$extraJemallocConfigureFlags"' !' /valkey/src/valkey/deps/Makefile; \
  grep -F "cd jemalloc && ./configure $extraJemallocConfigureFlags " /usr/src/valkey/deps/Makefile; \
  \
  export BUILD_TLS=yes; \
  make -C /usr/src/valkey -j "$(nproc)" all; \
  make -C /usr/src/valkey PREFIX=/opt/drycc/valkey install; \
  \
  # TODO https://github.com/redis/redis/pull/3494 (deduplicate "redis-server" copies)
  serverMd5="$(md5sum /opt/drycc/valkey/bin/valkey-server | cut -d' ' -f1)"; export serverMd5; \
  find /opt/drycc/valkey/bin/valkey* -maxdepth 0 \
    -type f -not -name valkey-server \
    -exec sh -eux -c ' \
      md5="$(md5sum "$1" | cut -d" " -f1)"; \
      test "$md5" = "$serverMd5"; \
    ' -- '{}' ';' \
    -exec ln -svfT 'valkey-server' '{}' ';' \
  ; \
  \
  rm -r /usr/src/valkey; \
  \
  apt-mark auto '.*' > /dev/null; \
  [ -z "$savedAptMark" ] || apt-mark manual $savedAptMark > /dev/null; \
  find /opt/drycc/valkey/bin -type f -executable -exec ldd '{}' ';' \
    | awk '/=>/ { print $(NF-1) }' \
    | sort -u \
    | xargs -r dpkg-query --search \
    | cut -d: -f1 \
    | sort -u \
    | xargs -r apt-mark manual \
  ; \
  apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false; \
  \
  /opt/drycc/valkey/bin/valkey-cli --version; \
  /opt/drycc/valkey/bin/valkey-server --version

  chmod +x /opt/drycc/valkey/bin/valkey*
  mkdir -p "${PROFILE_DIR}"
  cat  << EOF > "${PROFILE_DIR}/${STACK_NAME}.sh"
export PATH="/opt/drycc/valkey/bin:\$PATH"
EOF
  cp -rf /opt/drycc/valkey/* "${DATA_DIR}"
  VALKEY_MAJOR_VERSION=$(echo "${STACK_VERSION}" | awk -F "." '{print ""$1"."$2""}') 
  mkdir -p "${DATA_DIR}"/etc && \
  curl -fsSL -o "${DATA_DIR}"/etc/valkey-default.conf https://raw.githubusercontent.com/valkey-io/valkey/"${VALKEY_MAJOR_VERSION}"/valkey.conf
}

# call build stack
build-stack "${1}"
