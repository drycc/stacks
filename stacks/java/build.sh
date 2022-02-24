#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils


function get_openjdk_url() {
    version="${1:?version is required}"
    arch="$(dpkg --print-architecture)"
    if [[ "${version}" == "8" ]]; then
        case "$arch" in
            'amd64')
                 downloadUrl='https://github.com/AdoptOpenJDK/openjdk8-upstream-binaries/releases/download/jdk8u322-b06/OpenJDK8U-jdk_x64_linux_8u322b06.tar.gz';
                 ;;
            'arm64')
                downloadUrl='https://github.com/AdoptOpenJDK/openjdk8-upstream-binaries/releases/download/jdk8u322-b06/OpenJDK8U-jdk_aarch64_linux_8u322b06.tar.gz';
                ;;
            *) echo >&2 "error: unsupported architecture: '$arch'"; exit 1 ;;
        esac;
    elif [[ "${version}" == "11" ]]; then
        case "$arch" in
            'amd64')
                downloadUrl='https://github.com/AdoptOpenJDK/openjdk11-upstream-binaries/releases/download/jdk-11.0.14.1%2B1/OpenJDK11U-jdk_x64_linux_11.0.14.1_1.tar.gz';
                ;;
            'arm64')
                downloadUrl='https://github.com/AdoptOpenJDK/openjdk11-upstream-binaries/releases/download/jdk-11.0.14.1%2B1/OpenJDK11U-jdk_aarch64_linux_11.0.14.1_1.tar.gz';
                ;;
            *) echo >&2 "error: unsupported architecture: '$arch'"; exit 1;;
        esac
    elif [[ "${version}" == "17" ]]; then
        case "$arch" in
            'amd64')
                downloadUrl='https://download.java.net/java/GA/jdk17.0.2/dfd4a8d0985749f896bed50d7138ee7f/8/GPL/openjdk-17.0.2_linux-x64_bin.tar.gz';
                ;; \
            'arm64') \
                downloadUrl='https://download.java.net/java/GA/jdk17.0.2/dfd4a8d0985749f896bed50d7138ee7f/8/GPL/openjdk-17.0.2_linux-aarch64_bin.tar.gz';
                ;;
            *) echo >&2 "error: unsupported architecture: '$arch'"; exit 1 ;;
        esac;
    elif [[ "${version}" == "18" ]]; then
        case "$arch" in
            'amd64')
                downloadUrl='https://download.java.net/java/GA/jdk18/43f95e8614114aeaa8e8a5fcf20a682d/36/GPL/openjdk-18_linux-x64_bin.tar.gz';
                ;;
            'arm64')
                downloadUrl='https://download.java.net/java/GA/jdk18/43f95e8614114aeaa8e8a5fcf20a682d/36/GPL/openjdk-18_linux-aarch64_bin.tar.gz';
                ;;
            *) echo >&2 "error: unsupported architecture: '$arch'"; exit 1 ;;
        esac;
    elif [[ "${version}" == "19" ]]; then
        case "$arch" in
            'amd64')
                downloadUrl='https://download.java.net/java/early_access/jdk19/10/GPL/openjdk-19-ea+10_linux-x64_bin.tar.gz';
                ;;
            'arm64')
                downloadUrl='https://download.java.net/java/early_access/jdk19/10/GPL/openjdk-19-ea+10_linux-aarch64_bin.tar.gz';
                ;;
            *) echo >&2 "error: unsupported architecture: '$arch'"; exit 1 ;;
        esac;
    else
        echo >&2 "error: unsupported version: '$version'"
        exit 1
    fi
}

# Implement build function
function build() {
  generate-stack-path
  get_openjdk_url "${STACK_VERSION}"
  curl  -fsSL -o openjdk.tar.gz "${downloadUrl}"
  tar -xvzf openjdk.tar.gz
  cp -rf *jdk-"${STACK_VERSION}"*/* "${DATA_DIR}"
  rm -rf openjdk.tar.gz *jdk-"${STACK_VERSION}"*
  mkdir -p "${DATA_DIR}"/env
  echo "/opt/drycc/java" > "${DATA_DIR}"/env/JAVA_HOME
  cat  << EOF >> ${PROFILE_DIR}/${STACK_NAME}.sh
export LD_LIBRARY_PATH="\${JAVA_HOME}/jre/lib/${OS_ARCH}/server:\${LD_LIBRARY_PATH}"
EOF

}

# call build stack
build-stack "${1}"
