#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  cat << EOF > "${TARNAME}"/meta/dependencies
fuse-overlayfs
iptables
conmon
uidmap
slirp4netns
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
  tar -xzf tmp.tar.gz && rm tmp.tar.gz
  cd podman-${STACK_VERSION}
  

  sed -i "s#/etc/containers#/opt/drycc/podman/etc/containers#g" `grep /etc/containers -rl .`

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
  tar -xzf tmp.tar.gz
  rm tmp.tar.gz
  cd -

  chmod +x /opt/drycc/podman/bin/podman
  mkdir -p /opt/drycc/podman/etc/containers
  mkdir -p /opt/drycc/podman/run/containers/storage
  mkdir -p /opt/drycc/podman/var/lib/containers/storage
  mkdir -p /opt/drycc/podman/var/lib/shared
  mkdir -p /opt/drycc/podman/etc/cni/net.d

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
ignore_chown_errors = "true"
mount_program = "/usr/bin/fuse-overlayfs"
mountopt = "nodev,fsync=0"
EOF

  cat << EOF > "/opt/drycc/podman/etc/containers/containers.conf"
[containers]
netns="private"

[network]
cni_plugin_dir="/opt/drycc/podman/opt/cni"
network_config_dir="/opt/drycc/podman/etc/cni/net.d/"
default_network="podman"

[engine]
runtime="/opt/drycc/podman/bin/crun"
EOF

  curl -L -o /opt/drycc/podman/etc/containers/registries.conf https://src.fedoraproject.org/rpms/containers-common/raw/main/f/registries.conf
  curl -L -o /opt/drycc/podman/etc/containers/policy.json https://src.fedoraproject.org/rpms/containers-common/raw/main/f/default-policy.json
  cp -rf /opt/drycc/podman/* ${DATA_DIR}
}

# call build stack
build-stack "${1}"