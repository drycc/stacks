import os
import re
import json
import requests
from datetime import datetime

github_headers = {'Authorization': 'token %s' % os.environ.get("GITHUB_TOKEN")}

repo_info_table = {
    "vouch-proxy": {
        "name": "vouch-proxy",
        "type": "github",
        "owner": "vouch",
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
        "match": "^parent-[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "caddy": {
        "name": "caddy",
        "type": "github",
        "owner": "caddyserver",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "envtpl": {
        "name": "envtpl",
        "type": "github",
        "owner": "subfuzion",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "erlang": {
        "name": "otp",
        "type": "github",
        "owner": "erlang",
        "match": "^OTP-[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "fluentd": {
        "name": "fluentd",
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
    "jq": {
        "name": "jq",
        "type": "github",
        "owner": "stedolan",
        "match": "^jq-[0-9]{1,}\.[0-9]{1,}\.?[0-9]{0}$",
    },
    "kubectl": {
        "name": "kubectl",
        "type": "github",
        "owner": "kubernetes",
        "match": "^kubernetes-[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "mariadb": {
        "name": "server",
        "type": "github",
        "owner": "MariaDB",
        "match": "^mariadb-[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
    "mc": {
        "name": "mc",
        "type": "github",
        "owner": "minio",
        "match": "^RELEASE\.[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}-[0-9]{2}-[0-9]{2}Z$",
    },
    "minio": {
        "name": "minio",
        "type": "github",
        "owner": "minio",
        "match": "^RELEASE\.[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}-[0-9]{2}-[0-9]{2}Z$",
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
    "rabbitmq": {
        "name": "rabbitmq-server",
        "type": "github",
        "owner": "rabbitmq",
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
    "juicefs": {
        "name": "juicefs",
        "type": "github",
        "owner": "juicedata",
        "match": "^v[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}(-rc){0,1}[0-9]{0,}$",
    },
    "tikv": {
        "name": "tikv",
        "type": "github",
        "owner": "tikv",
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
    "zookeeper": {
        "name": "zookeeper",
        "type": "github",
        "owner": "apache",
        "match": "^release-[0-9]{1,}\.[0-9]{1,}\.[0-9]{1,}$",
    },
}


def create_github_tag(stack, tag_name):
    sha = requests.get(
        "https://api.github.com/repos/drycc/stacks/git/trees/main", 
        headers=github_headers,
    ).json()["sha"]
    response = requests.post(
        "https://api.github.com/repos/drycc/stacks/git/tags",
        data = json.dumps({
            "tag": tag_name,
            "object": sha,
            "message": f"new build for {stack}",
            "type": "commit",
        }),
        headers=github_headers,
    ).json()
    params = dict(ref=f"refs/tags/{tag_name}", sha=response['object']['sha'])
    response = requests.post(
        'https://api.github.com/repos/drycc/stacks/git/refs',
        data=json.dumps(params),
        headers=github_headers,
    )


def create_github_issue(stack, tag_name):
    strip_regex = "^[a-zA-Z\-_]{1,}"
    replace_regex = "[a-zA-Z\+\-_]{1,}"
    version = tag_name
    if re.search(strip_regex, tag_name):
        version = re.subn(strip_regex, "", tag_name)[0]
    if re.search(replace_regex, version):
        version = re.subn(replace_regex, ".", version)[0].strip(".")
    if requests.get(
        f"https://api.github.com/repos/drycc/stacks/git/ref/tags/{stack}@{version}",
        headers=github_headers,
    ).status_code == 404:
        create_github_tag(stack, f"{stack}@{version}")
        link = f"https://github.com/search?q=org%3Adrycc+install-stack+{stack}&type=code"
        requests.post(
            "https://api.github.com/repos/drycc/stacks/issues",
            data = json.dumps({
                "title": f"new build for {stack}@{version}",
                "body": f"Please judge whether the [referenced item]({link}) needs to be changed.",
                "labels": ["tag"]
            }),
            headers=github_headers,
        )


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

def check_github_version(stack):
    info = repo_info_table[stack]
    response = requests.post(
        "https://api.github.com/graphql",
        data=json.dumps({
            "query": github_tags_graphql.replace(
                "{owner}", info["owner"]).replace("{name}", info["name"]),
        }),
        headers=github_headers,
    )
    for tag in response.json()["data"]["repository"]["refs"]["edges"]:
        if "tagger" in tag["node"]["target"]:
            date = datetime.strptime(
                tag["node"]["target"]["tagger"]["date"][:19], "%Y-%m-%dT%H:%M:%S")
        else:
            date = datetime.strptime(
                requests.get(
                    "https://api.github.com/repos/{}/{}/commits/{}".format(
                        info["owner"], info["name"], tag["node"]["target"]["oid"]
                    ), headers=github_headers
                ).json()["commit"]["author"]["date"][:19],
                "%Y-%m-%dT%H:%M:%S"
            )
        if re.match(info["match"], tag["node"]["name"]):
            if (datetime.utcnow() - date).days < 5:
                create_github_issue(stack, tag["node"]["name"])
            else:
                break

def check_url_version(stack):
    info = repo_info_table[stack]
    html = requests.get(info["url"]).text
    versions = set()
    for url in set(re.findall(info["search"], html)):
        match = re.search(info["version"], url)
        if match:
            versions.add(match.group())
    for version in versions:
        create_github_issue(stack, version)


def main():
    for stack in os.listdir(os.path.join(os.path.dirname(__file__), "..", "stacks")):
        if stack not in repo_info_table:
            raise NotImplementedError(f"{stack} not in repo_info_table")
        else:
            repo_type = repo_info_table[stack]["type"]
            if repo_type == "github":
                check_github_version(stack)
            elif repo_type == 'url':
                check_url_version(stack)
            else:
                raise NotImplementedError(f"{repo_type} NotImplemented")


if __name__ == "__main__":
   main()
