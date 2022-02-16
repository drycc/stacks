#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  # Generate binary
  REDIS_DOWNLOAD_URL="http://download.redis.io/releases/redis-${STACK_VERSION}.tar.gz"
  savedAptMark="$(apt-mark showmanual)"; \
  curl -fsSL -o redis.tar.gz "$REDIS_DOWNLOAD_URL"; \
  mkdir -p /usr/src/redis; \
  tar -xzf redis.tar.gz -C /usr/src/redis --strip-components=1; \
  rm redis.tar.gz; \
  grep -E '^ *createBoolConfig[(]"protected-mode",.*, *1 *,.*[)],$' /usr/src/redis/src/config.c; \
  sed -ri 's!^( *createBoolConfig[(]"protected-mode",.*, *)1( *,.*[)],)$!\10\2!' /usr/src/redis/src/config.c; \
  grep -E '^ *createBoolConfig[(]"protected-mode",.*, *0 *,.*[)],$' /usr/src/redis/src/config.c; \
  gnuArch="$(dpkg-architecture --query DEB_BUILD_GNU_TYPE)"; \
  extraJemallocConfigureFlags="--build=$gnuArch"; \
  # https://salsa.debian.org/debian/jemalloc/-/blob/c0a88c37a551be7d12e4863435365c9a6a51525f/debian/rules#L8-23
  dpkgArch="$(dpkg --print-architecture)"; \
  case "${dpkgArch##*-}" in \
    amd64 | i386 | x32) extraJemallocConfigureFlags="$extraJemallocConfigureFlags --with-lg-page=12" ;; \
    *) extraJemallocConfigureFlags="$extraJemallocConfigureFlags --with-lg-page=16" ;; \
  esac; \
  extraJemallocConfigureFlags="$extraJemallocConfigureFlags --with-lg-hugepage=21"; \
  grep -F 'cd jemalloc && ./configure ' /usr/src/redis/deps/Makefile; \
  sed -ri 's!cd jemalloc && ./configure !&'"$extraJemallocConfigureFlags"' !' /usr/src/redis/deps/Makefile; \
  grep -F "cd jemalloc && ./configure $extraJemallocConfigureFlags " /usr/src/redis/deps/Makefile; \
  \
  export BUILD_TLS=yes; \
  make -C /usr/src/redis -j "$(nproc)" all; \
  make -C /usr/src/redis PREFIX=/opt/drycc/redis install; \
  \
  # TODO https://github.com/redis/redis/pull/3494 (deduplicate "redis-server" copies)
  serverMd5="$(md5sum /opt/drycc/redis/bin/redis-server | cut -d' ' -f1)"; export serverMd5; \
  find /opt/drycc/redis/bin/redis* -maxdepth 0 \
    -type f -not -name redis-server \
    -exec sh -eux -c ' \
      md5="$(md5sum "$1" | cut -d" " -f1)"; \
      test "$md5" = "$serverMd5"; \
    ' -- '{}' ';' \
    -exec ln -svfT 'redis-server' '{}' ';' \
  ; \
  \
  rm -r /usr/src/redis; \
  \
  apt-mark auto '.*' > /dev/null; \
  [ -z "$savedAptMark" ] || apt-mark manual $savedAptMark > /dev/null; \
  find /opt/drycc/redis/bin -type f -executable -exec ldd '{}' ';' \
    | awk '/=>/ { print $(NF-1) }' \
    | sort -u \
    | xargs -r dpkg-query --search \
    | cut -d: -f1 \
    | sort -u \
    | xargs -r apt-mark manual \
  ; \
  apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false; \
  \
  /opt/drycc/redis/bin/redis-cli --version; \
  /opt/drycc/redis/bin/redis-server --version

  chmod +x /opt/drycc/redis/bin/redis*
  mkdir -p "${PROFILE_DIR}"
  cat  << EOF > "${PROFILE_DIR}/${STACK_NAME}.sh"
export PATH="/opt/drycc/redis/bin:\$PATH"
EOF
  cp -rf /opt/drycc/redis/* "${DATA_DIR}"
}

# call build stack
build-stack "${1}"