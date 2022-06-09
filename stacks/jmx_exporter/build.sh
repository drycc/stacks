#!/bin/bash

# Load stack utils
. /usr/bin/stack-utils

# Implement build function
function build() {
  generate-stack-path
  BIN_DIR="${DATA_DIR}"/bin
  mkdir -p "${BIN_DIR}"
  curl -fsSL -o tmp.tar.gz https://github.com/prometheus/jmx_exporter/archive/refs/tags/parent-${STACK_VERSION}.tar.gz
  tar -xzf tmp.tar.gz
  mv jmx_exporter-parent-${STACK_VERSION}/example_configs/ "${DATA_DIR}"
  rm -rf jmx_exporter-parent-${STACK_VERSION} jmx_exporter-${STACK_VERSION}.linux-${OS_ARCH} tmp.tar.gz
  curl -fsSL -o "${DATA_DIR}"/jmx_prometheus_httpserver.jar https://repo1.maven.org/maven2/io/prometheus/jmx/jmx_prometheus_httpserver/${STACK_VERSION}/jmx_prometheus_httpserver-${STACK_VERSION}.jar
  curl -fsSL -o "${DATA_DIR}"/jmx_prometheus_javaagent.jar https://repo1.maven.org/maven2/io/prometheus/jmx/jmx_prometheus_javaagent/${STACK_VERSION}/jmx_prometheus_javaagent-${STACK_VERSION}.jar 
}

# call build stack
build-stack "${1}"
