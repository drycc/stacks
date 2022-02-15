#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  cat << EOF > "${TARNAME}"/meta/dependencies
fuse-overlayfs
iptables
conmon
libgpgme11
libdevmapper1.02.1
EOF

  install-packages \
    btrfs-progs \
    git \
    iptables \
    libassuan-dev \
    libbtrfs-dev \
    libc6-dev \
    libdevmapper-dev \
    libglib2.0-dev \
    libgpgme-dev \
    libgpg-error-dev \
    libprotobuf-dev \
    libprotobuf-c-dev \
    libseccomp-dev \
    libselinux1-dev \
    libsystemd-dev \
    pkg-config \
    runc \
    uidmap \
    conmon \
    go-md2man \
    libapparmor-dev
    
  install-stack go 1.17.7
  export GOPATH=/opt/drycc/go
  export PATH=$GOPATH/bin:$PATH

  curl -fsSL -o tmp.tar.gz https://github.com/containers/podman/archive/refs/tags/v${STACK_VERSION}.tar.gz
  tar -xvzf tmp.tar.gz && rm tmp.tar.gz
  cd podman-${STACK_VERSION}
  PREFIX=/opt/drycc/podman make BUILDTAGS="seccomp"
  PREFIX=/opt/drycc/podman make install
  cd /workspace
  rm -rf podman-${STACK_VERSION}
  
  crun_version=$(curl -Ls https://github.com/containers/crun/releases|grep /containers/crun/releases/tag/ | sed -E 's/.*\/containers\/crun\/releases\/tag\/([0-9\.]{1,}(-rc.[0-9]{1,})?)".*/\1/g' | head -1)
  curl -L -o /opt/drycc/podman/bin/crun https://github.com/containers/crun/releases/download/${crun_version}/crun-${crun_version}-linux-${OS_ARCH}
  chmod +x /opt/drycc/podman/bin/crun

  cni_version=$(curl -Ls https://github.com/containernetworking/plugins/releases|grep /containernetworking/plugins/releases/tag/ | sed -E 's/.*\/containernetworking\/plugins\/releases\/tag\/v([0-9\.]{1,}(-rc.[0-9]{1,})?)".*/\1/g' | head -1)
  mkdir -p /opt/drycc/podman/opt/cni/bin
  cd /opt/drycc/podman/opt/cni/bin
  curl -fsSL -o tmp.tar.gz https://github.com/containernetworking/plugins/releases/download/v${cni_version}/cni-plugins-linux-${OS_ARCH}-v${cni_version}.tgz
  tar -xvzf tmp.tar.gz
  rm tmp.tar.gz
  cd -

  mv /opt/drycc/podman/bin/podman /opt/drycc/podman/bin/podman-original
  cat << EOF > "/opt/drycc/podman/bin/podman"
if [ ! -d "/opt/cni" ];then
  ln -s /opt/drycc/podman/opt/cni /opt/cni
fi

if [ ! -d "/etc/containers" ];then
  ln -s /opt/drycc/podman/etc/containers /etc/containers
fi
exec /opt/drycc/podman/bin/podman-original --runtime /opt/drycc/podman/bin/crun "\$@"
EOF
  chmod +x /opt/drycc/podman/bin/podman
  mkdir -p /opt/drycc/podman/profile.d
  mkdir -p /opt/drycc/podman/etc/containers
  mkdir -p /opt/drycc/podman/run/containers/storage
  mkdir -p /opt/drycc/podman/var/lib/containers/storage
  mkdir -p /opt/drycc/podman/var/lib/shared
  cat << EOF > "/opt/drycc/podman/profile.d/podman.sh"
export PATH="/opt/drycc/podman/bin:\$PATH"
EOF
  cat << EOF > "/opt/drycc/podman/etc/containers/storage.conf"
[storage]
driver = "overlay"
runroot = "/opt/drycc/podman/run/containers/storage"
graphroot = "/opt/drycc/podman/var/lib/containers/storage"
[storage.options]
additionalimagestores = [
"/opt/drycc/podman/var/lib/shared",
]
[storage.options.overlay]
mount_program = "/usr/bin/fuse-overlayfs"
mountopt = "nodev,fsync=0"
EOF

  curl -L -o /opt/drycc/podman/etc/containers/registries.conf https://src.fedoraproject.org/rpms/containers-common/raw/main/f/registries.conf
  curl -L -o /opt/drycc/podman/etc/containers/policy.json https://src.fedoraproject.org/rpms/containers-common/raw/main/f/default-policy.json
  cp -rf /opt/drycc/podman "${TARNAME}"/data
}

# call build stack
build-stack "${1}"