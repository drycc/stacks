OTP_VERSION=${STACK_VERSION}
REBAR3_VERSION=$(curl -Ls https://github.com/erlang/rebar3/releases|grep /erlang/rebar3/releases/tag/ | sed -E 's/.*\/erlang\/rebar3\/releases\/tag\/([0-9\.]{1,}(-rc.[0-9]{1,})?)".*/\1/g' | head -1)

set -xe \
	&& OTP_DOWNLOAD_URL="https://github.com/erlang/otp/archive/OTP-${OTP_VERSION}.tar.gz" \
	&& runtimeDeps='libodbc1 libsctp1 libwxgtk3.0' \
	&& buildDeps='unixodbc-dev libsctp-dev libwxgtk-webview3.0-gtk3-dev' \
	&& apt-get update \
	&& apt-get install -y --no-install-recommends $runtimeDeps \
	&& apt-get install -y --no-install-recommends $buildDeps \
	&& curl -fSL -o otp-src.tar.gz "$OTP_DOWNLOAD_URL" \
	&& export ERL_TOP="/usr/src/otp_src_${OTP_VERSION%%@*}" \
	&& mkdir -vp $ERL_TOP \
	&& tar -xzf otp-src.tar.gz -C $ERL_TOP --strip-components=1 \
	&& rm otp-src.tar.gz \
	&& ( cd $ERL_TOP \
	  && ./otp_build autoconf \
	  && gnuArch="$(dpkg-architecture --query DEB_HOST_GNU_TYPE)" \
	  && ./configure --build="$gnuArch" --prefix=/opt/drycc/erlang \
	  && make -j$(nproc) \
	  && make -j$(nproc) docs DOC_TARGETS=chunks \
	  && make install install-docs DOC_TARGETS=chunks ) \
	&& find /opt/drycc/erlang -name examples | xargs rm -rf \
	&& apt-get purge -y --auto-remove $buildDeps \
	&& rm -rf $ERL_TOP /var/lib/apt/lists/*

set -xe \
	&& REBAR3_DOWNLOAD_URL="https://github.com/erlang/rebar3/archive/${REBAR3_VERSION}.tar.gz" \
	&& mkdir -p /usr/src/rebar3-src \
	&& curl -fSL -o rebar3-src.tar.gz "$REBAR3_DOWNLOAD_URL" \
	&& tar -xzf rebar3-src.tar.gz -C /usr/src/rebar3-src --strip-components=1 \
	&& rm rebar3-src.tar.gz \
	&& cd /usr/src/rebar3-src \
	&& HOME=$PWD ./bootstrap \
	&& install -v ./rebar3 /opt/drycc/erlang/bin/ \
	&& rm -rf /usr/src/rebar3-src