#!/usr/bin/env python3
"""
Clone every repo listed in repos.txt into src/<repo>/ and write repos.json.

repos.txt lines:
  owner: proofprotocol            all PUBLIC, non-fork, non-archived repos of this org/user
  include: someone/some-repo      one extra public repo
  exclude: proofprotocol/scratch  skip this repo
  # comments and blank lines are ignored

Private repos are never published, even if listed.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

CONFIG = Path(os.environ.get("REPOS_FILE", "repos.txt"))
SRC = Path(os.environ.get("SRC_DIR", "src"))
OUT_JSON = Path(os.environ.get("REPOS_JSON", "repos.json"))
TOKEN = os.environ.get("GH_TOKEN", "")
SELF = os.environ.get("GITHUB_REPOSITORY", "").lower()   # skip the hub repo itself


def api(path):
    req = urllib.request.Request(f"https://api.github.com{path}",
                                 headers={"Accept": "application/vnd.github+json",
                                          "User-Agent": "docs-hub"})
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def owner_repos(owner):
    for kind in ("orgs", "users"):
        out, page = [], 1
        try:
            while True:
                batch = api(f"/{kind}/{owner}/repos?type=public&per_page=100&page={page}")
                if not batch:
                    break
                out += batch
                page += 1
            return out
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            raise
    print(f"WARN: owner not found: {owner}", file=sys.stderr)
    return []


def main():
    owners, includes, excludes = [], [], set()
    for line in CONFIG.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        k, v = (x.strip() for x in line.split(":", 1))
        if k == "owner":
            owners.append(v)
        elif k == "include":
            includes.append(v)
        elif k == "exclude":
            excludes.add(v.lower())

    repos = {}
    for o in owners:
        for r in owner_repos(o):
            repos[r["full_name"].lower()] = r
    for full in includes:
        try:
            r = api(f"/repos/{full}")
            repos[r["full_name"].lower()] = r
        except urllib.error.HTTPError as e:
            print(f"WARN: cannot read {full}: {e.code}", file=sys.stderr)

    SRC.mkdir(parents=True, exist_ok=True)
    meta, used = {}, set()
    for full, r in sorted(repos.items()):
        if full in excludes or full == SELF or r.get("private") or r.get("fork") or r.get("archived"):
            continue
        folder = r["name"] if r["name"].lower() not in used else r["full_name"].replace("/", "-")
        used.add(folder.lower())
        dest = SRC / folder
        if dest.exists():
            subprocess.run(["rm", "-rf", str(dest)], check=True)
        res = subprocess.run(["git", "clone", "--quiet", "--filter=blob:none",
                              "--branch", r["default_branch"], r["clone_url"], str(dest)],
                             capture_output=True, text=True)
        if res.returncode != 0:
            print(f"WARN: clone failed {full}: {res.stderr.strip()}", file=sys.stderr)
            continue
        meta[folder] = {"url": r["html_url"], "branch": r["default_branch"],
                        "description": r.get("description") or ""}
        print(f"cloned {full} -> {dest}")

    OUT_JSON.write_text(json.dumps(meta, indent=2))
    print(f"{len(meta)} repos ready")


if __name__ == "__main__":
    main()
