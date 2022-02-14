
export PATH=/opt/drycc/python/bin:$PATH
export LANG=C.UTF-8

# build dependencies
install-packages \
    gpg-agent \
    dirmngr \
    gpg \
    wget \
	libbluetooth-dev \
	tk-dev \
	uuid-dev

export GPG_KEY=A035C8C19219BA821ECEA86B64E628F8D684696D
export PYTHON_VERSION=${STACK_VERSION}
export PATH=/opt/drycc/python/bin:$PATH

set -eux; \
	\
	wget -O python.tar.xz "https://www.python.org/ftp/python/${PYTHON_VERSION%%[a-z]*}/Python-$PYTHON_VERSION.tar.xz"; \
	wget -O python.tar.xz.asc "https://www.python.org/ftp/python/${PYTHON_VERSION%%[a-z]*}/Python-$PYTHON_VERSION.tar.xz.asc"; \
	GNUPGHOME="$(mktemp -d)"; export GNUPGHOME; \
	gpg --batch --keyserver hkps://keys.openpgp.org --recv-keys "$GPG_KEY"; \
	gpg --batch --verify python.tar.xz.asc python.tar.xz; \
	command -v gpgconf > /dev/null && gpgconf --kill all || :; \
	rm -rf "$GNUPGHOME" python.tar.xz.asc; \
	mkdir -p /usr/src/python; \
	tar --extract --directory /usr/src/python --strip-components=1 --file python.tar.xz; \
	rm python.tar.xz; \
	\
	cd /usr/src/python; \
	gnuArch="$(dpkg-architecture --query DEB_BUILD_GNU_TYPE)"; \
	./configure \
	    --prefix=/opt/drycc/python \
		--build="$gnuArch" \
		--enable-loadable-sqlite-extensions \
		--enable-optimizations \
		--enable-option-checking=fatal \
		--enable-shared \
		--with-lto \
		--with-system-expat \
		--with-system-ffi \
		--without-ensurepip \
	; \
	nproc="$(nproc)"; \
	make -j "$nproc" \
	; \
	make install; \
	cd /; \
	rm -rf /usr/src/python; \
	\
	find /opt/drycc/python -depth \
		\( \
			\( -type d -a \( -name test -o -name tests -o -name idle_test \) \) \
			-o \( -type f -a \( -name '*.pyc' -o -name '*.pyo' -o -name '*.a' \) \) \
		\) -exec rm -rf '{}' + \
	; \
	\
	ldconfig; \
	\
	python3 --version

# make some useful symlinks that are expected to exist ("/opt/drycc/python/bin/python" and friends)
set -eux; \
	for src in idle3 pydoc3 python3 python3-config; do \
		dst="$(echo "$src" | tr -d 3)"; \
		[ -s "/opt/drycc/python/bin/$src" ]; \
		[ ! -e "/opt/drycc/python/bin/$dst" ]; \
		ln -svT "/opt/drycc/python/bin/$src" "/opt/drycc/python/bin/$dst"; \
	done

# https://github.com/pypa/get-pip
export PYTHON_GET_PIP_URL=https://github.com/pypa/get-pip/raw/main/public/get-pip.py

set -eux; \
	\
	wget -O get-pip.py "$PYTHON_GET_PIP_URL"; \
	\
	python get-pip.py \
		--disable-pip-version-check \
		--no-cache-dir \
	; \
	pip --version; \
	\
	find /opt/drycc/python -depth \
		\( \
			\( -type d -a \( -name test -o -name tests -o -name idle_test \) \) \
			-o \
			\( -type f -a \( -name '*.pyc' -o -name '*.pyo' \) \) \
		\) -exec rm -rf '{}' + \
	; \
	rm -f get-pip.py