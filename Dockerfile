ARG CODENAME
ARG DRYCC_REGISTRY
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
        cmake \
		autoconf \
		automake \
		bzip2 \
		dpkg-dev \
		file \
		g++ \
		gcc \
		clang \
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
        python3-venv \
		libucl-dev \
        default-libmysqlclient-dev; \
	python3 -m venv /usr/local/python

ENV PATH "/usr/local/python/bin:${PATH}"

RUN UPX_VERSION=4.1.0; \
  OS_ARCH=$(dpkg --print-architecture); \
  wget https://github.com/upx/upx/releases/download/v${UPX_VERSION}/upx-${UPX_VERSION}-${OS_ARCH}_linux.tar.xz; \
  tar -Jxvf upx-${UPX_VERSION}-${OS_ARCH}_linux.tar.xz; \
  cp upx-${UPX_VERSION}-${OS_ARCH}_linux/upx /usr/local/bin; \
  rm -rf upx-*; \
  pip install oss2 packaging;
