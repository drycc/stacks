install-stack ruby "${RUBY_VERSION}"
. /opt/drycc/ruby/profile.d/*.sh

jemalloc_version=$(curl -Ls https://github.com/jemalloc/jemalloc/releases|grep /jemalloc/jemalloc/releases/tag/ | sed -E 's/.*\/jemalloc\/jemalloc\/releases\/tag\/([0-9\.]{1,})".*/\1/g' | head -1)

apt-get update \
 && apt-get install -y --no-install-recommends \
            ca-certificates \
 && buildDeps=" \
      make gcc g++ libc-dev \
      wget bzip2 gnupg dirmngr \
    " \
 && apt-get install -y --no-install-recommends $buildDeps \
 && echo 'gem: --no-document' >> /etc/gemrc \
 && gem install oj \
 && gem install json \
 && gem install async-http \
 && gem install fluentd -v ${STACK_VERSION} \
 && wget -O /tmp/jemalloc-${jemalloc_version}.tar.bz2 https://github.com/jemalloc/jemalloc/releases/download/${jemalloc_version}/jemalloc-${jemalloc_version}.tar.bz2 \
 && cd /tmp && tar -xjf jemalloc-${jemalloc_version}.tar.bz2 && cd jemalloc-${jemalloc_version}/ \
 && ./configure && make \
 && mkdir -p /opt/drycc/fluentd/lib \
 && mv lib/libjemalloc.so.2 /opt/drycc/fluentd/lib \
 && apt-get purge -y --auto-remove \
                  -o APT::AutoRemove::RecommendsImportant=false \
                  $buildDeps \
 && rm -rf /var/lib/apt/lists/* \
 && rm -rf /tmp/* /var/tmp/*