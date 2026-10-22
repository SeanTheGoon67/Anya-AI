#!/usr/bin/env python
"""
release.py — cut a GitHub release for Anya, with files attached.

Usage:
    python tools/release.py v0.19.0 notes.md [file ...]

`gh` is not required: this talks to the REST API directly, taking the token
from Git Credential Manager (the same stored credential `git push` uses).

Assets are the whole point of this script. An earlier one-off version accepted
a filename argument and then ignored it, so every release looked published while
having *no* attached APK — always confirm with the printed `asset status` line,
or check the release page.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

REPO = "SeanTheGoon67/Anya-AI"
GCM_CANDIDATES = (
    r"C:\Program Files\Git\mingw64\bin\git-credential-manager.exe",
    r"C:\Program Files\Git\mingw64\bin\git-credential-manager-core.exe",
)


def token() -> str:
    """The stored GitHub token, from Git Credential Manager."""
    for exe in GCM_CANDIDATES:
        if not os.path.exists(exe):
            continue
        out = subprocess.run([exe, "get"], input="protocol=https\nhost=github.com\n\n",
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            if line.startswith("password="):
                return line.split("=", 1)[1].strip()
    env = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if env:
        return env
    raise SystemExit("no GitHub token: push once so git saves a credential, "
                     "or set GITHUB_TOKEN")


def api(url: str, data=None, method=None) -> tuple:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "Bearer " + token())
    req.add_header("Accept", "application/vnd.github+json")
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def upload(rel: dict, path: str) -> None:
    """Attach one file. Uploads go to uploads.github.com, not api.github.com."""
    name = os.path.basename(path)
    if any(a.get("name") == name for a in rel.get("assets", [])):
        print(f"asset already attached: {name}")
        return
    url = rel["upload_url"].split("{")[0] + "?name=" + urllib.parse.quote(name)
    with open(path, "rb") as fh:
        data = fh.read()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", "Bearer " + token())
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/octet-stream")
    req.add_header("Content-Length", str(len(data)))
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            got = json.loads(r.read().decode() or "{}")
            size = got.get("size", 0)
            ok = "ok" if size == len(data) else f"SIZE MISMATCH ({size} != {len(data)})"
            print(f"asset status: {r.status}  {name}  {size} bytes  [{ok}]")
            if size != len(data):
                raise SystemExit("asset upload was truncated")
    except urllib.error.HTTPError as e:
        print(f"asset FAILED: {e.code} {e.read().decode()[:300]}")
        raise SystemExit(1)


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    tag = sys.argv[1]
    notes = open(sys.argv[2], encoding="utf-8").read()
    files = sys.argv[3:]

    st, rel = api(f"https://api.github.com/repos/{REPO}/releases/tags/{tag}")
    if st == 200:
        print(f"release {tag} already exists: {rel.get('html_url')}")
    else:
        st, rel = api(f"https://api.github.com/repos/{REPO}/releases", {
            "tag_name": tag,
            "target_commitish": "main",
            "name": f"Anya {tag}",
            "body": notes,
            "draft": False,
            "prerelease": False,
        })
        print("create status:", st)
        if st not in (200, 201):
            print(json.dumps(rel, indent=2)[:800])
            return 1
        print("release:", rel["html_url"])

    for path in files:
        upload(rel, path)

    desc = ("Local coding AI for Windows - a fine-tuned Qwen2.5-Coder that runs "
            "entirely on your PC. Own GUI, power limiter for gaming, Projects "
            "sandbox that builds real APKs, phone access, an installable phone "
            f"app with voice, self-update. {tag}")
    st, r = api(f"https://api.github.com/repos/{REPO}", {"description": desc})
    print("description status:", st)

    if not files:
        print("warning: no files were attached to this release")
    return 0


if __name__ == "__main__":
    sys.exit(main())
