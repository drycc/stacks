ARG CODENAME DRYCC_REGISTRY
FROM ${DRYCC_REGISTRY}/drycc/base:${CODENAME}

RUN install-packages \
        ca-certificates \
		curl \
		netbase \
		wget \
		gnupg \
		dirmngr

RUN install-packages \
		git \
		mercurial \
		openssh-client \
		subversion \
		procps

RUN install-packages \
		autoconf \
		automake \
		bzip2 \
		dpkg-dev \
		file \
		g++ \
		gcc \
		imagemagick \
		libbz2-dev \
		libc6-dev \
		libcurl4-openssl-dev \
		libdb-dev \
		libevent-dev \
		libffi-dev \
		libgdbm-dev \
		libglib2.0-dev \
		libgmp-dev \
		libjpeg-dev \
		libkrb5-dev \
		liblzma-dev \
		libmagickcore-dev \
		libmagickwand-dev \
		libmaxminddb-dev \
		libncurses5-dev \
		libncursesw5-dev \
		libpng-dev \
		libpq-dev \
		libreadline-dev \
		libsqlite3-dev \
		libssl-dev \
		libtool \
		libwebp-dev \
		libxml2-dev \
		libxslt-dev \
		libyaml-dev \
		make \
		patch \
		unzip \
		xz-utils \
		zlib1g-dev \
        python3-pip \
		libucl-dev \
        default-libmysqlclient-dev; \
    pip install oss2
# build upx
RUN git clone https://github.com/upx/upx; \
  cd upx; git submodule update --init --recursive; make all UPX_UCLDIR=../ucl-1.03 CXXFLAGS_OPTIMIZE="-no-pie -O2"; cd -; \
  cp upx/src/upx.out /usr/local/bin/upx; \
  rm -rf ucl-1.03 ucl-1.03.tar.gz upx;