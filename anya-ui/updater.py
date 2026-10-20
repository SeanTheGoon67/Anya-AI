#!/usr/bin/env python
"""
updater.py — keep a GitHub copy of Anya up to date (standard library only).

For people who cloned Anya from GitHub, "update" means a fast-forward pull.
For anyone running from a plain download, we fall back to fetching the release
zip and laying the source files over the current folder — never touching your
own config, chats, models, LoRA adapters, training data or saved library.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
VERSION_FILE = PROJECT / "VERSION"
ANYA_REPO = "SeanTheGoon67/Anya-AI"
GIT_URL = f"https://github.com/{ANYA_REPO}.git"
API = "https://api.github.com/repos/" + ANYA_REPO

# never overwritten by the zip overlay: your data, not the app's code
KEEP_TOP = {"config.json", "approvals.json", "current.txt", "anya_chats.db"}
KEEP_DIRS = {"models", "lora", "dataset", "site", "tools", "voices", ".git",
             "anya-publish", "__pycache__"}

# code files that must never be replaced with an empty/older copy
KEEP_SUFFIX = (".gguf", ".safetensors", ".bin", ".db", ".log", ".wav", ".mp3")

_cache: dict = {"at": 0.0, "data": None}
_cache_lock = threading.Lock()


def cached() -> dict:
    """The last update check, or None if we've never looked."""
    with _cache_lock:
        return _cache["data"]


def local_version() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
    except Exception:                                             # noqa: BLE001
        return "0.0.0"


def git_path() -> str:
    found = shutil.which("git")
    if found:
        return found
    for p in (r"C:\Program Files\Git\cmd\git.exe",
              r"C:\Program Files (x86)\Git\cmd\git.exe"):
        if os.path.exists(p):
            return p
    return ""


def is_git_repo() -> bool:
    return (PROJECT / ".git").is_dir() and bool(git_path())


def _no_window() -> int:
    return 0x08000000 if os.name == "nt" else 0


def _git(*args: str) -> tuple:
    exe = git_path()
    if not exe:
        return 1, "git is not installed"
    try:
        p = subprocess.run([exe, "-C", str(PROJECT), *args], capture_output=True,
                           text=True, timeout=120, creationflags=_no_window())
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as exc:                                      # noqa: BLE001
        return 1, str(exc)


def _get(url: str, token: str = "") -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Anya-UI",
        "Accept": "application/vnd.github+json",
    })
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _api(paths: list, token: str = "") -> dict:
    last = ""
    for url in paths:
        try:
            return json.loads(_get(url, token).decode("utf-8"))
        except Exception as exc:                                  # noqa: BLE001
            last = str(exc)
    raise RuntimeError(last or "GitHub request failed")


def _ver_tuple(v: str) -> tuple:
    parts = []
    for bit in str(v).lstrip("vV").split("."):
        num = "".join(ch for ch in bit if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple((parts + [0, 0, 0])[:3])


def check(token: str = "", force: bool = False, ttl: int = 1800) -> dict:
    """Return update status. Cached for `ttl` seconds unless force=True."""
    now = time.time()
    with _cache_lock:
        if not force and _cache["data"] and now - _cache["at"] < ttl:
            return _cache["data"]

    current = local_version()
    info = {
        "current": current, "latest": current, "has_update": False,
        "notes": "", "url": f"https://github.com/{ANYA_REPO}/releases",
        "repo": ANYA_REPO, "method": "git" if is_git_repo() else "zip",
        "checked": now, "error": "", "git_dirty": False, "branch": "",
    }
    try:
        rel = _api([f"{API}/releases/latest", f"{API}/releases"], token)
        if isinstance(rel, list):
            rel = rel[0] if rel else {}
        tag = (rel.get("tag_name") or rel.get("name") or "").lstrip("vV")
        if tag:
            info["latest"] = tag
            info["notes"] = (rel.get("body") or "").strip()
            info["url"] = rel.get("html_url") or info["url"]
        info["has_update"] = _ver_tuple(tag or current) > _ver_tuple(current)
    except Exception as exc:                                      # noqa: BLE001
        info["error"] = f"couldn't reach GitHub ({exc})"

    if is_git_repo():
        rc, out = _git("rev-parse", "--abbrev-ref", "HEAD")
        if rc == 0:
            info["branch"] = out.strip()
        rc, out = _git("status", "--porcelain")
        info["git_dirty"] = bool(rc == 0 and out.strip())
        _, remote = _git("rev-parse", "HEAD")
        info["commit"] = remote[:8]

    with _cache_lock:
        _cache["at"] = now
        _cache["data"] = info
    return info


def _invalidate() -> None:
    with _cache_lock:
        _cache["data"] = None


def apply(token: str = "") -> dict:
    """Update the app. Returns {ok, method, output}."""
    if is_git_repo():
        res = apply_git()
    else:
        res = apply_zip(token)
    _invalidate()
    return res


def apply_git() -> dict:
    out = []
    rc, o = _git("fetch", "--tags", "--prune")
    out.append(f"$ git fetch --tags\n{o}")
    if rc != 0:
        return {"ok": False, "method": "git", "output": "\n\n".join(out)}
    rc, o = _git("pull", "--ff-only")
    out.append(f"$ git pull --ff-only\n{o}")
    return {"ok": rc == 0, "method": "git", "output": "\n\n".join(out)}


def apply_zip(token: str = "") -> dict:
    """Download the newest source zip and overlay the app's files."""
    info = check(token, force=True)
    tag = info.get("latest") or "main"
    candidates = [
        f"https://github.com/{ANYA_REPO}/archive/refs/tags/v{tag}.zip",
        f"https://github.com/{ANYA_REPO}/archive/refs/tags/{tag}.zip",
        f"https://github.com/{ANYA_REPO}/archive/refs/heads/main.zip",
    ]
    blob = None
    used = ""
    err = ""
    for url in candidates:
        try:
            blob = _get(url, token)
            used = url
            break
        except Exception as exc:                                  # noqa: BLE001
            err = str(exc)
    if blob is None:
        return {"ok": False, "method": "zip", "output": f"download failed: {err}"}

    updated = []
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            zf.extractall(tmp)
        roots = [p for p in Path(tmp).iterdir() if p.is_dir()]
        if not roots:
            return {"ok": False, "method": "zip", "output": "empty archive"}
        src = roots[0]
        for item in src.rglob("*"):
            rel = item.relative_to(src)
            if item.is_dir():
                continue
            if rel.parts and rel.parts[0] in KEEP_DIRS:
                continue
            if len(rel.parts) == 1 and rel.name in KEEP_TOP:
                continue
            if rel.suffix.lower() in KEEP_SUFFIX:
                continue
            dest = PROJECT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                if not dest.exists() or dest.read_bytes() != item.read_bytes():
                    shutil.copy2(item, dest)
                    updated.append(str(rel))
            except Exception:                                     # noqa: BLE001
                pass
    return {"ok": True, "method": "zip",
            "output": f"updated {len(updated)} file(s) from {used}\n"
                      + "\n".join(updated[:200])}
