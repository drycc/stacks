#!/bin/bash

curl -fsSL -o nginx.tar.gz http://nginx.org/download/nginx-${STACK_VERSION}.tar.gz
tar -xvzf nginx.tar.gz
cd nginx-${STACK_VERSION}
./configure \
  --prefix=/opt/drycc/nginx \
  --with-threads \
  --with-file-aio \
  --with-http_ssl_module \
  --with-http_v2_module \
  --with-pcre-jit
make
make install
rm -rf /workspace/nginx.tar.gz /workspace/nginx-${STACK_VERSION}