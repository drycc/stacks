#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  cat << EOF > "${TARNAME}"/meta/dependencies
iptables
uidmap
EOF

  install-packages \
    man \
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
    libapparmor-dev \
    protobuf-compiler
  
  install-stack go "${GO_VERSION}"
  install-stack rust "${RUST_VERSION}"
  . init-stack

  git clone -b v${STACK_VERSION} --dept=1 https://github.com/containers/podman podman-${STACK_VERSION}
  cd podman-${STACK_VERSION}
  PREFIX=/opt/drycc/podman make BUILDTAGS="seccomp"
  PREFIX=/opt/drycc/podman make install
  cd /workspace
  rm -rf podman-${STACK_VERSION}
  
  crun_version=$(curl -Ls https://github.com/containers/crun/releases|grep /containers/crun/releases/tag/ | sed -E 's/.*\/containers\/crun\/releases\/tag\/([0-9\.]{1,}(-rc.[0-9]{1,})?)".*/\1/g' | head -1)
  curl -L -o /opt/drycc/podman/bin/crun https://github.com/containers/crun/releases/download/${crun_version}/crun-${crun_version}-linux-${OS_ARCH}
  chmod +x /opt/drycc/podman/bin/crun

  # network
  netavark_version=$(curl -Ls https://github.com/containers/netavark/releases|grep /containers/netavark/releases/tag/ | sed -E 's/.*\/containers\/netavark\/releases\/tag\/v([0-9\.]{1,}[0-9]{1,}?)".*/\1/g' | head -1)
  git clone -b v${netavark_version} --dept=1 https://github.com/containers/netavark
  cd netavark; make; cp ./bin/* /opt/drycc/podman/libexec/podman
  cd -; rm -rf netavark

  # slirp4netns
  slirp4netns_version=$(curl -Ls https://github.com/rootless-containers/slirp4netns/releases|grep /rootless-containers/slirp4netns/releases/tag/ | sed -E 's/.*\/rootless-containers\/slirp4netns\/releases\/tag\/v([0-9\.]{1,}[0-9]{1,}?)".*/\1/g' | head -1)
  curl -o /opt/drycc/podman/libexec/podman/slirp4netns --fail -L https://github.com/rootless-containers/slirp4netns/releases/download/v${slirp4netns_version}/slirp4netns-$(uname -m)
  chmod +x /opt/drycc/podman/libexec/podman/slirp4netns

  # fuse-overlayfs
  fuse_overlayfs_version=$(curl -Ls https://github.com/containers/fuse-overlayfs/releases|grep /containers/fuse-overlayfs/releases/tag/ | sed -E 's/.*\/containers\/fuse-overlayfs\/releases\/tag\/v([0-9\.]{1,}[0-9]{1,}?)".*/\1/g' | head -1)
  curl -o /opt/drycc/podman/libexec/podman/fuse-overlayfs --fail -L https://github.com/containers/fuse-overlayfs/releases/download/v${fuse_overlayfs_version}/fuse-overlayfs-$(uname -m)
  chmod +x /opt/drycc/podman/libexec/podman/fuse-overlayfs

  # conmon
  conmon_version=$(curl -Ls https://github.com/containers/conmon/releases|grep /containers/conmon/releases/tag/ | sed -E 's/.*\/containers\/conmon\/releases\/tag\/v([0-9\.]{1,}[0-9]{1,}?)".*/\1/g' | head -1)
  curl -o /opt/drycc/podman/libexec/podman/conmon --fail -L https://github.com/containers/conmon/releases/download/v${conmon_version}/conmon.$(dpkg --print-architecture)
  chmod +x /opt/drycc/podman/libexec/podman/conmon

  chmod +x /opt/drycc/podman/bin/podman
  mkdir -p /opt/drycc/podman/etc/containers
  mkdir -p /opt/drycc/podman/run/containers/storage
  mkdir -p /opt/drycc/podman/var/lib/containers/storage
  mkdir -p /opt/drycc/podman/var/lib/shared
  mkdir -p /opt/drycc/podman/etc/netavark/net.d

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
mount_program = "/opt/drycc/podman/libexec/podman/fuse-overlayfs"
mountopt = "nodev,fsync=0"
EOF

  cat << EOF > "/opt/drycc/podman/etc/containers/containers.conf"
[containers]
netns="private"

[network]
network_config_dir="/opt/drycc/podman/etc/netavark/net.d/"
default_network="podman"
default_rootless_network_cmd="slirp4netns"

[engine]
runtime="/opt/drycc/podman/bin/crun"
conmon_path=[
  "/opt/drycc/podman/libexec/podman/conmon",
]
helper_binaries_dir=[
  "/opt/drycc/podman/libexec/podman",
]
EOF
  
  cat << EOF > "/opt/drycc/podman/etc/containers/policy.json"
{
    "default": [
        {
            "type": "insecureAcceptAnything"
        }
    ]
}
EOF

  cat << EOF > "/opt/drycc/podman/etc/containers/registries.conf"
unqualified-search-registries = ["docker.io"]
EOF

  mkdir -p /opt/drycc/podman/profile.d
  cat << EOF > /opt/drycc/podman/profile.d/config.sh
if [[ "\$(id -u)" = "0" ]]; then
    PODMAN_CONFIG_DIR=/etc/containers
else
    PODMAN_CONFIG_DIR=\${HOME}/.config/containers
fi
rm -rf "\${PODMAN_CONFIG_DIR}"
mkdir -p "\${PODMAN_CONFIG_DIR}"
cp /opt/drycc/podman/etc/containers/* "\${PODMAN_CONFIG_DIR}"
EOF

  cp -rf /opt/drycc/podman/* ${DATA_DIR}

}

# call build stack
build-stack "${1}"
