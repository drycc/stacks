import os
import re
import json
import requests
from datetime import datetime, timezone
from packaging.version import InvalidVersion, parse


# The shared retention rule: every (stack, version series) keeps the
# newest N versions. The reconcile planner only builds inside these
# per-series windows and the OSS cleaner only deletes outside them, so
# cleanup never schedules a rebuild.
DEFAULT_RETENTION = 2


github_headers = {'Authorization': 'token %s' % os.environ.get("GITHUB_TOKEN")}

repo_info_table = {
    "alertmanager": {
        "name": "alertmanager",
        "type": "github",
        "owner": "prometheus",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "redis_exporter": {
        "name": "redis_exporter",
        "type": "github",
        "owner": "oliver006",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "mysqld_exporter": {
        "name": "mysqld_exporter",
        "type": "github",
        "owner": "prometheus",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "postgres_exporter": {
        "name": "postgres_exporter",
        "type": "github",
        "owner": "prometheus-community",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "jmx_exporter": {
        "name": "jmx_exporter",
        "type": "github",
        "owner": "prometheus",
        "match": "^[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "caddy": {
        "name": "caddy",
        "type": "github",
        "owner": "caddyserver",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "erlang": {
        "name": "otp",
        "type": "github",
        "owner": "erlang",
        "match": "^OTP-[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "etcd": {
        "name": "etcd",
        "type": "github",
        "owner": "etcd-io",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "fluentd": {
        "name": "fluentd",
        "type": "github",
        "owner": "fluent",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "fluent-bit": {
        "name": "fluent-bit",
        "type": "github",
        "owner": "fluent",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "go": {
        "name": "go",
        "type": "github",
        "owner": "golang",
        "match": "^go[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "gosu": {
        "name": "gosu",
        "type": "github",
        "owner": "tianon",
        "match": "^[0-9]{1,}\.[0-9]{1,}$",
    },
    "grafana": {
        "name": "grafana",
        "type": "github",
        "owner": "grafana",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "helm": {
        "name": "helm",
        "type": "github",
        "owner": "helm",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "ini-file": {
        "name": "ini-file",
        "type": "github",
        "owner": "bitnami",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "java": {
        "url": "https://learn.microsoft.com/en-us/java/openjdk/download",
        "type": "url",
        "search": r"https://aka.ms/download-jdk/microsoft-jdk-[0-9]{1,}.[0-9]{1,}.[0-9]{1,}-linux-x64.tar.gz",
        "version": r"[0-9]{1,}.[0-9]{1,}.[0-9]{1,}",
    },
    "netcat": {
        "url": "https://sourceforge.net/projects/netcat/files/netcat",
        "type": "url",
        "search": r"netcat-[0-9]{1,}.[0-9]{1,}.[0-9]{1,}.tar.bz2",
        "version": r"[0-9]{1,}.[0-9]{1,}.[0-9]{1,}",
    },
    "jq": {
        "name": "jq",
        "type": "github",
        "owner": "jqlang",
        "match": r"^jq-[0-9]+\.[0-9]+(?:\.[0-9]+)?$",
    },
    "kvrocks": {
        "name": "kvrocks",
        "type": "github",
        "owner": "apache",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "kvrocks_exporter": {
        "name": "kvrocks_exporter",
        "type": "github",
        "owner": "RocksLabs",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "kubectl": {
        "name": "kubectl",
        "type": "github",
        "owner": "kubernetes",
        "match": "^kubernetes-[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "nginx": {
        "name": "nginx",
        "type": "github",
        "owner": "nginx",
        "match": "^release-[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "node": {
        "name": "node",
        "type": "github",
        "owner": "nodejs",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "pack": {
        "name": "pack",
        "type": "github",
        "owner": "buildpacks",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "php": {
        "name": "php-src",
        "type": "github",
        "owner": "php",
        "match": "^php-[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "podman": {
        "name": "podman",
        "type": "github",
        "owner": "containers",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "postgresql": {
        "name": "postgres",
        "type": "github",
        "owner": "postgres",
        "match": "^REL_[0-9]{1,}_[0-9]{1,}$",
    },
    "python": {
        "name": "cpython",
        "type": "github",
        "owner": "python",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "quickwit": {
        "name": "quickwit",
        "type": "github",
        "owner": "quickwit-oss",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "rabbitmq": {
        "name": "rabbitmq-server",
        "type": "github",
        "owner": "rabbitmq",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "rclone": {
        "name": "rclone",
        "type": "github",
        "owner": "rclone",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "redis": {
        "name": "redis",
        "type": "github",
        "owner": "redis",
        "match": "^[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "redis-sentinel": {
        "name": "redis",
        "type": "github",
        "owner": "redis",
        "match": "^[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "valkey": {
        "name": "valkey",
        "type": "github",
        "owner": "valkey-io",
        "match": "^[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "valkey-sentinel-proxy": {
        "name": "valkey-sentinel-proxy",
        "type": "github",
        "owner": "drycc-addons",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "registry": {
        "name": "distribution",
        "type": "github",
        "owner": "distribution",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "ruby": {
        "name": "ruby",
        "type": "github",
        "owner": "ruby",
        "match": "^v[0-9]{1,}_[0-9]{1,}_[0-9]{1,}$",
    },
    "rust": {
        "name": "rust",
        "type": "github",
        "owner": "rust-lang",
        "match": "^[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "telegraf": {
        "name": "telegraf",
        "type": "github",
        "owner": "influxdata",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "wait-for-port": {
        "name": "wait-for-port",
        "type": "github",
        "owner": "bitnami",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "render-template": {
        "name": "render-template",
        "type": "github",
        "owner": "bitnami",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "wal-g": {
        "name": "wal-g",
        "type": "github",
        "owner": "wal-g",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.?[0-9]{0}$",
    },
    "yj": {
        "name": "yj",
        "type": "github",
        "owner": "sclevine",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "yq": {
        "name": "yq",
        "type": "github",
        "owner": "mikefarah",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "prometheus": {
        "name": "prometheus",
        "type": "github",
        "owner": "prometheus",
        "match": "^v[2-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "node_exporter": {
        "name": "node_exporter",
        "type": "github",
        "owner": "prometheus",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "kube-state-metrics": {
        "name": "kube-state-metrics",
        "type": "github",
        "owner": "kubernetes",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "mysql": {
        "name": "mysql-server",
        "type": "github",
        "owner": "mysql",
        "match": "^mysql-[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "mysql-shell": {
        "name": "mysql-shell",
        "type": "github",
        "owner": "mysql",
        "match": "^[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "zookeeper": {
        "name": "zookeeper",
        "type": "github",
        "owner": "apache",
        "match": "^release-[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "spark": {
        "name": "spark",
        "type": "github",
        "owner": "apache",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "flink": {
        "name": "flink",
        "type": "github",
        "owner": "apache",
        "match": "^release-[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "opensearch": {
        "name": "OpenSearch",
        "type": "github",
        "owner": "opensearch-project",
        "match": "^[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "opensearch-dashboards": {
        "name": "OpenSearch-Dashboards",
        "type": "github",
        "owner": "opensearch-project",
        "match": "^[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "rustfs": {
        "name": "rustfs",
        "type": "github",
        "owner": "rustfs",
        "match": "^[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "opentelemetry-collector": {
        "name": "opentelemetry-collector-releases",
        "type": "github",
        "owner": "open-telemetry",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "statsd_exporter": {
        "name": "statsd_exporter",
        "type": "github",
        "owner": "prometheus",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "kafka_exporter": {
        "name": "kafka_exporter",
        "type": "github",
        "owner": "danielqsj",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "kafka": {
        "name": "kafka",
        "type": "github",
        "owner": "apache",
        "match": "^[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "envoy": {
        "name": "envoy",
        "type": "github",
        "owner": "envoyproxy",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "mongodb": {
        "name": "mongo",
        "type": "github",
        "owner": "mongodb",
        "match": "^r[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "mongosh": {
        "name": "mongosh",
        "type": "github",
        "owner": "mongodb-js",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "mongodb_exporter": {
        "name": "mongodb_exporter",
        "type": "github",
        "owner": "percona",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "clickhouse": {
        "name": "ClickHouse",
        "type": "github",
        "owner": "ClickHouse",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}.[0-9]{1,}-lts$",
    },
    "nessie": {
        "name": "nessie",
        "type": "github",
        "owner": "projectnessie",
        "match": "^nessie-[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "lakefs": {
        "name": "lakefs",
        "type": "github",
        "owner": "treeverse",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "victoriametrics": {
        "name": "victoriametrics",
        "type": "github",
        "owner": "victoriametrics",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "headscale": {
        "name": "headscale",
        "type": "github",
        "owner": "juanfont",
        "match": "v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "tailscale": {
        "name": "tailscale",
        "type": "github",
        "owner": "tailscale",
        "match": "v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
}


def normalize_version(tag_name):
    """Extract the stack version from an upstream tag name."""
    strip_regex = "^[a-zA-Z\-_]{1,}"
    replace_regex = "[a-zA-Z\+\-_]{1,}"
    version = tag_name
    if re.search(strip_regex, tag_name):
        version = re.subn(strip_regex, "", tag_name)[0]
    if re.search(replace_regex, version):
        version = re.subn(replace_regex, ".", version)[0].strip(".")
    return version


def parse_object_key(key):
    """stacks/<stack>/<stack>-<version>-linux-<arch>-<flavour>.tar.gz ->
    (stack, version, arch, flavour), or None when the key does not
    follow the artifact layout (directory markers, foreign names).

    The version is whatever sits between "<stack>-" and "-linux-" so
    hyphenated stack names stay intact, and the flavour is the rest of
    the tail so hyphenated flavours do too. Shared by the planner and
    the cleaner so both interpret OSS objects identically.
    """
    if not key.startswith("stacks/") or not key.endswith(".tar.gz"):
        return None
    parts = key.split("/")
    if len(parts) != 3:
        return None
    stack, basename = parts[1], parts[2]
    if not basename.startswith(stack + "-"):
        return None
    body = basename[len(stack) + 1:]
    version, marker, tail = body.partition("-linux-")
    if not marker:
        return None
    arch, sep, flavour = tail.removesuffix(".tar.gz").partition("-")
    if not sep or arch not in ("amd64", "arm64") or not flavour:
        return None
    return stack, version, arch, flavour


def version_series(value):
    """Return the retention series: drop only the final dot-separated
    component. For example 13.4 -> 13, 8.0.1 -> 8.0 and 4.52 -> 4.
    A value without a dot is its own series.
    """
    head, separator, _ = value.rpartition(".")
    return head if separator else value


def retention_keep(versions, count=DEFAULT_RETENTION):
    """Return the versions kept by the shared retention rule: the newest
    `count` versions by semantic order (packaging.version.parse), newest
    first.

    The reconcile planner and the OSS cleaner both use this semantic
    ordering helper within each version series. The planner rolls forward
    from the newest object in the same series, so a version pruned by the
    cleaner is never selected for rebuilding. Semantic order (not
    lexicographic) matters: "1.10.0" is newer than "1.9.0".

    Versions that cannot be parsed are always kept: their age is
    unknown, so dropping them would be a guess.
    """
    if count < 1:
        raise ValueError("retention count must be at least 1")
    ranked = []
    unknown = []
    for value in versions:
        try:
            ranked.append((parse(value), value))
        except InvalidVersion:
            unknown.append(value)
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [value for _, value in ranked[:count]] + unknown


github_tags_graphql = """
query {
  repository(owner: "{owner}", name: "{name}") {
    refs(refPrefix: "refs/tags/", first: 10, orderBy: {field: TAG_COMMIT_DATE, direction: DESC}) {
      edges {
        node {
          name
          target {
            oid
            ... on Tag {
              commitUrl
              tagger {
                date
              }
            }
          }
        }
      }
    }
  }
}
"""

def _tag_date(tag, info, session):
    target = tag["node"]["target"]
    if "tagger" in target:
        raw = target["tagger"]["date"]
    else:
        response = session.get(
            "https://api.github.com/repos/{}/{}/commits/{}".format(
                info["owner"], info["name"], target["oid"]
            ),
            headers=github_headers,
        )
        raw = response.json()["commit"]["author"]["date"]
    return datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def _github_candidates(stack, info, session):
    response = session.post(
        "https://api.github.com/graphql",
        data=json.dumps({
            "query": github_tags_graphql.replace(
                "{owner}", info["owner"]).replace("{name}", info["name"]),
        }),
        headers=github_headers,
    )
    candidates = []
    seen = set()
    for tag in response.json()["data"]["repository"]["refs"]["edges"]:
        name = tag["node"]["name"]
        if not re.match(info["match"], name):
            continue
        version = normalize_version(name)
        if version in seen:
            continue
        seen.add(version)
        candidates.append({
            "stack": stack,
            "version": version,
            "upstream": name,
            "date": _tag_date(tag, info, session),
        })
    return candidates


def _url_candidates(stack, info, session):
    html = session.get(info["url"]).text
    versions = set()
    for url in set(re.findall(info["search"], html)):
        match = re.search(info["version"], url)
        if match:
            versions.add(match.group())
    return [
        {"stack": stack, "version": version, "upstream": version, "date": None}
        for version in sorted(versions, reverse=True)
    ]


def discover_candidates(stack, session=None):
    """Discover upstream release candidates for a stack (read-only).

    Returns a list of candidates, newest first for github stacks, each a
    dict with "stack", "version" (normalized), "upstream" (raw tag name)
    and "date" (aware datetime, or None for url stacks). Never creates
    tags or issues in drycc/stacks.
    """
    info = repo_info_table[stack]
    if session is None:
        session = requests
    if info["type"] == "github":
        return _github_candidates(stack, info, session)
    if info["type"] == "url":
        return _url_candidates(stack, info, session)
    raise NotImplementedError(f"{info['type']} NotImplemented")

