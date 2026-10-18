#!/usr/bin/env python
"""learn.py — Anya reads whole GitHub repositories into a local library.

A user pastes a repo, and this module:

    1. asks GitHub for the repo (owner, default branch, size, public/private);
    2. downloads the whole tree as one tarball (one request, no per-file crawl);
    3. unpacks *text* files into a folder under the library root, skipping the
       things that are useless to a code model (binaries, images, vendored and
       generated trees) and capping sizes so a giant repo cannot fill the disk;
    4. writes a small keyword index so the app can pull the handful of files
       that matter into Anya's context when she is asked about them.

Two honest points, because they shape the design:

    * Reading a repo does *not* train the model. It is retrieval: the app puts
      the relevant files in her context for one answer. The saved files are also
      plain text on disk, so the real fine-tune pipeline in dataset/ can consume
      them later (export_dataset() writes that JSONL for you).
    * A repo is untrusted input. Extraction refuses absolute paths, `..`,
      symlinks and hard links, and caps file count, per-file size and total size.

This module is deliberately stdlib-only and has no dependency on anya_ui, in the
same spirit as web.py and projects.py.

Public surface
--------------
    configure(state_dir, library_root, dataset_dir)   point the module at its folders
    root() / set_root(path)                           the library folder
    token() / set_token(str)                          a GitHub token (private repos)
    parse_spec(text)                                  'owner/repo@ref' from a URL or slug
    wants_repo(text)                                  a repo the user named in a message
    fetch_repo(spec, on_event)                        download + unpack + index one repo
    list_repos()                                      summaries, newest first
    get_repo(rid)                                     one repo: manifest + files
    list_files(rid)                                   files kept from a repo
    read_file(rid, rel)                               one file's text
    delete_repo(rid)                                  remove a repo from the library
    reveal(rid)                                       open its folder in the file manager
    recall(query, limit)                              the files most relevant to a question
    export_dataset(rid, path)                         turn a repo into training JSONL
    parse_tool_call(text)                             Anya's recall / learn_repo JSON
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = "Anya/1.0 (local GitHub reader; +https://github.com)"

API = "https://api.github.com"
CODELOAD = "https://codeload.github.com"

MAX_DOWNLOAD = 400_000_000         # refuse a tarball bigger than this (bytes)
MAX_FILE_BYTES = 200_000           # a single text file we keep
MAX_FILES = 4_000                  # files kept per repo
MAX_TOTAL_BYTES = 250_000_000      # total unpacked text kept per repo
MAX_READ_CHARS = 40_000            # returned to the UI / to Anya
MAX_LIST = 800                     # files listed for the UI
RECALL_FILES = 4                   # files handed to Anya per question
RECALL_BUDGET = 7_000              # characters of library text per question
RECALL_SNIPPET = 2_600             # characters kept from one recalled file
INDEX_TERMS = 40                   # terms remembered per file
DOWNLOAD_TIMEOUT = 180

# Trees that never help a code model and can be enormous.
SKIP_DIRS = {
    ".git", ".github", ".gradle", ".idea", ".vscode", ".anya", ".venv", "venv",
    "node_modules", "bower_components", "vendor", "third_party", "__pycache__",
    "build", "dist", "out", "bin", "obj", "target", "coverage", ".next", ".nuxt",
    ".cache", ".tox", ".mypy_cache", ".pytest_cache", "site-packages", "Pods",
}

# Generated / minified files carry no teaching value.
SKIP_SUFFIX = (".min.js", ".min.css", ".map", ".lock", "-lock.json")

TEXT_EXT = {
    ".kt", ".kts", ".java", ".xml", ".gradle", ".properties", ".toml", ".cfg",
    ".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".json",
    ".md", ".markdown", ".rst", ".txt", ".text", ".yaml", ".yml", ".ini",
    ".sh", ".bash", ".zsh", ".bat", ".cmd", ".ps1", ".c", ".h", ".cpp", ".hpp",
    ".cc", ".cxx", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".m", ".mm",
    ".sql", ".html", ".htm", ".css", ".scss", ".sass", ".less", ".vue", ".svelte",
    ".lua", ".dart", ".pl", ".pm", ".r", ".proto", ".cmake", ".mk", ".make",
    ".gradle.kts", ".gitignore", ".dockerignore", ".editorconfig", ".env.example",
    ".csv", ".tsv", ".graphql", ".gql", ".tf", ".hcl", ".nix", ".ex", ".exs",
    ".erl", ".hs", ".lhs", ".clj", ".cljs", ".scala", ".groovy", ".asm", ".s",
    ".f90", ".jl", ".nim", ".zig", ".v", ".vb", ".fs", ".fsx", ".pas", ".tex",
}

# Extension-less files worth keeping.
TEXT_NAMES = {
    "makefile", "dockerfile", "readme", "license", "licence", "changelog",
    "contributing", "gemfile", "rakefile", "procfile", "jenkinsfile", "notice",
    "authors", "codeowners", "go.mod", "go.sum", "cargo.toml",
}
DOT_FILES = {".gitignore", ".dockerignore", ".editorconfig", ".gitattributes",
             ".env.example", ".npmrc"}

# Words that carry no search signal.
STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "any", "can", "had",
    "her", "was", "one", "our", "out", "day", "get", "has", "him", "his", "how",
    "its", "new", "now", "old", "see", "two", "way", "who", "boy", "did", "use",
    "she", "that", "with", "this", "from", "they", "have", "will", "your", "what",
    "when", "make", "like", "time", "just", "know", "take", "into", "than", "them",
    "then", "some", "could", "would", "there", "their", "about", "which", "these",
    "value", "class", "import", "public", "private", "return", "void", "string",
    "true", "false", "null", "var", "val", "fun", "def", "self", "int", "bool",
    "override", "object", "package", "final", "static", "const", "let", "function",
}


class LearnError(Exception):
    """Something went wrong that is worth telling the user about."""


# --- configuration ----------------------------------------------------------

_STATE_DIR: Path | None = None
_ROOT: Path = Path(r"S:\anya-library")
_DATASET_DIR: Path = Path("dataset")
_TOKEN: str = ""
_INDEX_CACHE: dict[str, list[dict]] = {}


def configure(state_dir, library_root=None, dataset_dir=None) -> None:
    """Point the module at its folders. Called once at start-up."""
    global _STATE_DIR, _DATASET_DIR
    _STATE_DIR = Path(state_dir)
    if library_root:
        set_root(library_root)
    if dataset_dir:
        _DATASET_DIR = Path(dataset_dir)


def root() -> Path:
    return _ROOT


def set_root(library_root) -> Path:
    global _ROOT
    _ROOT = Path(library_root)
    _INDEX_CACHE.clear()
    return _ROOT


def token() -> str:
    return _TOKEN


def set_token(value: str) -> None:
    global _TOKEN
    _TOKEN = (value or "").strip()


def _ensure_root() -> Path:
    _ROOT.mkdir(parents=True, exist_ok=True)
    return _ROOT


def enabled() -> bool:
    """The module is always importable; the app decides whether to call it."""
    return True


# --- ids and paths ----------------------------------------------------------

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").strip().lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)[:48].strip("-") or "repo"


def _repo_id(owner: str, repo: str) -> str:
    return f"{_slug(owner)}__{_slug(repo)}"


def _repo_dir(rid: str) -> Path:
    if not _ID_RE.match(rid or "") or ".." in rid:
        raise LearnError(f"bad library id: {rid!r}")
    return _ROOT / rid


def _files_dir(rid: str) -> Path:
    return _repo_dir(rid) / "files"


def _manifest_path(rid: str) -> Path:
    return _repo_dir(rid) / "library.json"


def _index_path(rid: str) -> Path:
    return _repo_dir(rid) / "index.jsonl"


def _load(rid: str) -> dict:
    mp = _manifest_path(rid)
    if not mp.exists():
        raise LearnError(f"no such repo in the library: {rid}")
    try:
        data = json.loads(mp.read_text(encoding="utf-8"))
    except Exception as exc:                                      # noqa: BLE001
        raise LearnError(f"{rid} has an unreadable manifest ({exc})") from None
    data["id"] = rid
    return data


def _save(rid: str, data: dict) -> None:
    _ensure_root()
    _repo_dir(rid).mkdir(parents=True, exist_ok=True)
    _manifest_path(rid).write_text(json.dumps(data, indent=2), encoding="utf-8")


# --- reading a repo name out of text ----------------------------------------

# github.com/owner/repo  ·  owner/repo  ·  git@github.com:owner/repo.git
_GH_URL = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com[/:](?P<owner>[A-Za-z0-9][\w.-]{0,38})/"
    r"(?P<repo>[A-Za-z0-9_.-]{1,100}?)(?:\.git)?"
    r"(?:/(?:tree|blob)/(?P<ref>[^\s/?#]+)(?P<path>/[^\s?#]*)?)?(?=[\s?#]|$)",
    re.I)
_SLUG = re.compile(r"^(?P<owner>[A-Za-z0-9][\w.-]{0,38})/(?P<repo>[A-Za-z0-9_.-]{1,100})$")


def parse_spec(text: str) -> dict | None:
    """Pull {owner, repo, ref, url} out of a URL, a slug or a git remote.

    Returns None for anything that isn't a recognisable GitHub repo. The ref
    comes from a /tree/<branch> URL when there is one; otherwise it is empty and
    the caller uses the repo's default branch.
    """
    t = (text or "").strip().strip("<>\"'`")
    if not t:
        return None
    m = _GH_URL.search(text)
    if m:
        owner = m.group("owner")
        repo = re.sub(r"\.git$", "", m.group("repo"))
        if owner.lower() in ("orgs", "orgs", "topics", "collections", "search",
                             "marketplace", "sponsors", "features", "settings"):
            return None
        ref = m.group("ref") or ""
        return {"owner": owner, "repo": repo, "ref": ref,
                "url": f"https://github.com/{owner}/{repo}"}
    m = _SLUG.match((text or "").strip())
    if m:
        return {"owner": m.group("owner"), "repo": m.group("repo"),
                "ref": "", "url": f"https://github.com/{m.group('owner')}/{m.group('repo')}"}
    return None


def parse_spec_and_ref(text: str) -> tuple[dict | None, str]:
    """parse_spec plus an explicit '@ref' the user may have appended."""
    text = (text or "").strip()
    ref = ""
    m = re.search(r"@([\w./-]{1,80})\s*$", text)
    if m and "github.com" not in text[:m.start()].lower():
        ref = m.group(1)
        text = text[:m.start()].strip()
    spec = parse_spec(text)
    if spec and not spec.get("ref"):
        spec["ref"] = ref
    return spec, ref


def wants_repo(text: str) -> dict | None:
    """The repo a chat message names, if the message actually points at GitHub."""
    if not text or "github" not in text.lower():
        return None
    spec, _ = parse_spec_and_ref(text)
    return spec


# --- talking to GitHub ------------------------------------------------------

def _request(url: str, *, accept: str = "application/vnd.github+json",
             auth: bool = True, max_bytes: int = MAX_DOWNLOAD):
    """GET a URL with Anya's headers and (optionally) the GitHub token."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    if auth and _TOKEN:
        req.add_header("Authorization", f"Bearer {_TOKEN}")
    opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
    try:
        with opener.open(req, timeout=DOWNLOAD_TIMEOUT) as resp:
            return resp.read(max_bytes + 1), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise LearnError(
                "GitHub refused that request. For a private repo, add a personal "
                "access token in Settings. (Public repos also hit a rate limit if "
                "you read many in an hour.)") from None
        if exc.code == 404:
            raise LearnError("GitHub says that repo doesn't exist (or is private "
                             "and needs a token in Settings).") from None
        raise LearnError(f"GitHub answered with HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise LearnError(f"couldn't reach GitHub ({exc.reason})") from None
    except LearnError:
        raise
    except Exception as exc:                                      # noqa: BLE001
        raise LearnError(f"the request failed ({type(exc).__name__}: {exc})") from None


def _api(path: str) -> dict:
    raw, _ = _request(API + path, max_bytes=2_000_000)
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception:                                             # noqa: BLE001
        raise LearnError("GitHub sent something that wasn't JSON") from None
    if isinstance(data, dict) and data.get("message"):
        raise LearnError(f"GitHub: {data['message']}")
    return data


def _download_tarball(owner: str, repo: str, ref: str, private: bool) -> bytes:
    """One request for the whole tree. Codeload for public, the API for private."""
    if private or _TOKEN:
        url = f"{API}/repos/{owner}/{repo}/tarball/{urllib.parse.quote(ref)}"
        accept = "application/vnd.github+json"
    else:
        url = f"{CODELOAD}/{owner}/{repo}/tar.gz/{urllib.parse.quote(ref)}"
        accept = "application/octet-stream"
    data, _ = _request(url, accept=accept, max_bytes=MAX_DOWNLOAD)
    if len(data) > MAX_DOWNLOAD:
        raise LearnError("that repo is too big to read in one go")
    if not data:
        raise LearnError("GitHub returned an empty archive")
    return data


# --- unpacking safely --------------------------------------------------------

def _keep(path: str) -> bool:
    """True if a path is a text file worth keeping."""
    name = path.rsplit("/", 1)[-1]
    lower = name.lower()
    if lower in TEXT_NAMES or lower in DOT_FILES:
        return True
    for suffix in SKIP_SUFFIX:
        if lower.endswith(suffix):
            return False
    if lower.startswith("."):
        return False
    if lower.endswith(".gradle.kts"):
        return True
    return os.path.splitext(lower)[1] in TEXT_EXT


def _looks_binary(chunk: bytes) -> bool:
    return b"\x00" in chunk[:2048]


def _safe_member(name: str) -> str | None:
    """A member's path relative to the repo root, or None if we must refuse it."""
    name = name.replace("\\", "/").lstrip("/")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    # tarballs from GitHub start with a single "owner-repo-sha/" component
    rel = "/".join(parts[1:]) if len(parts) > 1 else ""
    if not rel:
        return None
    if any(p in SKIP_DIRS for p in rel.split("/")[:-1]):
        return None
    return rel


def _ingest(data: bytes, owner: str, repo: str, ref: str, private: bool,
            on_event=None) -> dict:
    """Unpack a tarball into the library and write its manifest and index.

    Kept separate from the network so it can be tested with a hand-built archive.
    """
    say = on_event or (lambda **k: None)
    rid = _repo_id(owner, repo)
    _ensure_root()
    dest = _repo_dir(rid)
    staging = _ROOT / f".incoming-{rid}"
    shutil.rmtree(staging, ignore_errors=True)
    (staging / "files").mkdir(parents=True, exist_ok=True)

    kept: list[dict] = []
    index_rows: list[str] = []
    total = 0
    seen = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
            for member in tar:
                if not member.isfile():
                    continue                    # skips dirs, symlinks and hard links
                seen += 1
                rel = _safe_member(member.name)
                if not rel or not _keep(rel):
                    continue
                if member.size > MAX_FILE_BYTES:
                    continue
                if len(kept) >= MAX_FILES or total >= MAX_TOTAL_BYTES:
                    break
                try:
                    fh = tar.extractfile(member)
                    if fh is None:
                        continue
                    raw = fh.read(MAX_FILE_BYTES + 1)
                except (tarfile.TarError, OSError):
                    continue
                if len(raw) > MAX_FILE_BYTES or _looks_binary(raw):
                    continue
                text = raw.decode("utf-8", "replace")
                out = staging / "files" / Path(*rel.split("/"))
                try:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(text, encoding="utf-8")
                except OSError:
                    continue
                nbytes = len(text.encode("utf-8"))
                total += nbytes
                kept.append({"path": rel, "bytes": nbytes})
                index_rows.append(json.dumps(
                    {"path": rel, "bytes": nbytes,
                     "terms": _term_counts(text, INDEX_TERMS)}, ensure_ascii=False))
                if len(kept) % 250 == 0:
                    say(kind="progress", files=len(kept), path=rel)
        if not kept:
            raise LearnError(
                "that repo has no readable text files (only binaries, images or "
                "generated code)")
    except tarfile.TarError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise LearnError(f"the archive was unreadable ({exc})") from None
    except LearnError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except Exception as exc:                                      # noqa: BLE001
        shutil.rmtree(staging, ignore_errors=True)
        raise LearnError(f"unpacking failed ({type(exc).__name__}: {exc})") from None

    # write the index next to the files
    (staging / "index.jsonl").write_text("\n".join(index_rows), encoding="utf-8")

    manifest = {
        "id": rid, "owner": owner, "repo": repo, "ref": ref or "HEAD",
        "url": f"https://github.com/{owner}/{repo}", "private": bool(private),
        "fetched": time.time(), "files": len(kept), "seen": seen,
        "bytes": sum(f["bytes"] for f in kept),
        "kept": kept[:600],
    }
    (staging / "library.json").write_text(json.dumps(manifest, indent=2),
                                          encoding="utf-8")

    shutil.rmtree(dest, ignore_errors=True)
    os.replace(staging, dest)
    _INDEX_CACHE.pop(rid, None)
    return manifest


# --- the public fetch --------------------------------------------------------

def fetch_repo(text, on_event=None) -> dict:
    """Read a whole repo into the library. `text` is a URL, owner/repo, or a spec."""
    say = on_event or (lambda **k: None)
    if isinstance(text, dict):
        spec = dict(text)
    else:
        spec, _ref = parse_spec_and_ref(text)
    if not spec or not spec.get("owner") or not spec.get("repo"):
        raise LearnError("that doesn't look like a GitHub repo "
                         "(try github.com/owner/name)")
    owner, repo = spec["owner"], spec["repo"]

    say(kind="note", text=f"Looking up {owner}/{repo} …")
    meta = _api(f"/repos/{owner}/{repo}")
    private = bool(meta.get("private"))
    if private and not _TOKEN:
        raise LearnError(f"{owner}/{repo} is private — add a GitHub token in Settings.")
    ref = spec.get("ref") or meta.get("default_branch") or "main"
    size_kb = int(meta.get("size") or 0)
    if size_kb > 2_000_000:                       # ~2 GB, over the download cap
        raise LearnError(f"{owner}/{repo} looks too large to read "
                         f"({size_kb // 1024} MB). Try a smaller repo.")

    say(kind="note", text=f"Downloading {owner}/{repo}@{ref} "
                          f"({'private' if private else 'public'}) …")
    data = _download_tarball(owner, repo, ref, private)
    say(kind="note", text=f"Unpacking {len(data) // 1024} KB of archive …")
    manifest = _ingest(data, owner, repo, ref, private, on_event=say)
    say(kind="done", **{k: manifest[k] for k in ("id", "files", "bytes")})
    return manifest


# --- listing and reading -----------------------------------------------------

def _summary(man: dict) -> dict:
    return {"id": man.get("id", ""), "owner": man.get("owner", ""),
            "repo": man.get("repo", ""), "ref": man.get("ref", ""),
            "url": man.get("url", ""), "files": man.get("files", 0),
            "bytes": man.get("bytes", 0), "fetched": man.get("fetched", 0),
            "private": bool(man.get("private"))}


def list_repos() -> list[dict]:
    if not _ROOT.exists():
        return []
    out = []
    for child in _ROOT.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        mp = child / "library.json"
        if not mp.exists():
            continue
        try:
            man = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:                                         # noqa: BLE001
            continue
        man["id"] = child.name
        out.append(_summary(man))
    out.sort(key=lambda r: r.get("fetched", 0), reverse=True)
    return out


def get_repo(rid: str) -> dict:
    man = _load(rid)
    return {"id": man["id"], "owner": man["owner"], "repo": man["repo"],
            "ref": man["ref"], "url": man["url"], "private": bool(man["private"]),
            "fetched": man["fetched"], "files": man["files"], "bytes": man["bytes"],
            "path": str(_repo_dir(rid).resolve()),
            "listing": list_files(rid), "truncated": man["files"] > MAX_LIST}


def list_files(rid: str, limit: int = MAX_LIST) -> list[dict]:
    base = _files_dir(rid)
    if not base.exists():
        return []
    out: list[dict] = []
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(base).as_posix()
        except ValueError:
            continue
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        out.append({"path": rel, "bytes": size})
        if len(out) >= limit:
            break
    return out


def read_file(rid: str, rel: str, max_chars: int = MAX_READ_CHARS) -> dict:
    target = _resolve(rid, rel)
    if not target.is_file():
        raise LearnError(f"no such file: {rel}")
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise LearnError(f"couldn't read that file ({exc})") from None
    return {"repo": rid, "path": rel.replace("\\", "/"),
            "text": text[:max_chars], "truncated": len(text) > max_chars}


def _resolve(rid: str, rel: str) -> Path:
    """A file inside a repo's files/ folder, or refuse."""
    base = _files_dir(rid)
    raw = (rel or "").strip().replace("\\", "/").lstrip("/")
    if not raw:
        raise LearnError("empty path")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise LearnError(f"bad path: {rel!r}")
    target = base.joinpath(*parts)
    try:
        target.resolve().relative_to(base.resolve())
    except ValueError:
        raise LearnError(f"bad path: {rel!r}") from None
    return target


def delete_repo(rid: str) -> None:
    d = _repo_dir(rid)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    _INDEX_CACHE.pop(rid, None)


def reveal(rid: str) -> str:
    """Open a repo's folder in the desktop file manager."""
    d = _repo_dir(rid)
    if not d.exists():
        raise LearnError(f"there is no folder for {rid}")
    try:
        if hasattr(os, "startfile"):
            os.startfile(str(d))                          # noqa: S606
        else:
            opener = "open" if os.uname().sysname == "Darwin" else "xdg-open"
            subprocess.Popen([opener, str(d)])            # noqa: S603,S607
    except OSError as exc:
        raise LearnError(f"couldn't open the folder: {exc}") from exc
    return str(d)


# --- recall: which files matter for a question -------------------------------

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,31}")


def _terms(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text or "")
            if w.lower() not in STOPWORDS and len(w) > 2]


def _term_counts(text: str, keep: int = INDEX_TERMS) -> dict:
    counts: dict[str, int] = {}
    for w in _terms(text):
        counts[w] = counts.get(w, 0) + 1
    if len(counts) <= keep:
        return counts
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:keep]
    return dict(top)


def _index(rid: str) -> list[dict]:
    if rid in _INDEX_CACHE:
        return _INDEX_CACHE[rid]
    rows: list[dict] = []
    ip = _index_path(rid)
    if ip.exists():
        try:
            for line in ip.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:                                 # noqa: BLE001
                    continue
        except OSError:
            rows = []
    _INDEX_CACHE[rid] = rows
    return rows


def recall(query: str, limit: int = RECALL_FILES,
           budget: int = RECALL_BUDGET) -> list[dict]:
    """The files most relevant to a question, with a short excerpt of each.

    Pure keyword scoring: a term found in a file's body counts once per hit; a
    term found in its path counts for far more, because "MainActivity.kt" is a
    stronger signal than the word appearing anywhere. Good enough to pick four
    files out of a few thousand, and it costs nothing at query time.
    """
    q = set(_terms(query))
    if not q:
        return []
    scored: list[tuple[float, str, str]] = []
    for repo in list_repos():
        rid = repo["id"]
        for row in _index(rid):
            terms = row.get("terms") or {}
            hit = q & terms.keys()
            if not hit:
                continue
            path_l = (row.get("path") or "").lower()
            score = sum(terms.get(t, 0) for t in hit)
            for t in hit:
                if t in path_l:
                    score += 8
            if score:
                scored.append((score, rid, row.get("path") or ""))
    scored.sort(key=lambda s: s[0], reverse=True)

    out: list[dict] = []
    used = 0
    for _score, rid, path in scored:
        if len(out) >= limit or used >= budget:
            break
        try:
            text = read_file(rid, path, max_chars=RECALL_SNIPPET)["text"]
        except LearnError:
            continue
        room = max(400, budget - used)
        text = text[:room]
        used += len(text)
        man = _safe_manifest(rid)
        out.append({"repo": f'{man.get("owner", "")}/{man.get("repo", "")}'.strip("/"),
                    "id": rid, "path": path, "text": text})
    return out


def _safe_manifest(rid: str) -> dict:
    try:
        return _load(rid)
    except LearnError:
        return {}


# --- exporting a training corpus ---------------------------------------------

def export_dataset(rid: str | None = None, path=None, max_chars: int = 4_000) -> dict:
    """Write alpaca-style JSONL (instruction / input / output) for a fine-tune.

    One pair per kept file, matching the shape of the existing dataset/*.jsonl,
    so it can be dropped straight into the training pipeline. With no `rid`,
    every repo in the library is exported into one file.
    """
    repos = [_load(rid)] if rid else [_load(r["id"]) for r in list_repos()]
    if not repos:
        raise LearnError("the library is empty — read a repo first")
    if path is None:
        _DATASET_DIR.mkdir(parents=True, exist_ok=True)
        path = _DATASET_DIR / (f"library_{rid}.jsonl" if rid else "library_all.jsonl")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    entries = 0
    with path.open("w", encoding="utf-8") as fh:
        for man in repos:
            rid2 = man["id"]
            slug = f'{man.get("owner", "")}/{man.get("repo", "")}'
            for fi in list_files(rid2, limit=10 ** 9):
                rel = fi["path"]
                try:
                    text = read_file(rid2, rel, max_chars=max_chars)["text"]
                except LearnError:
                    continue
                if len(text.strip()) < 40:
                    continue
                rec = {
                    "instruction": (f"Show the code in {rel} from the "
                                    f"{slug} repository, and explain what it does."),
                    "input": "",
                    "output": text,
                }
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                entries += 1
    return {"path": str(path), "entries": entries}


# --- Anya's tiny tool protocol -----------------------------------------------

_RECALL_WORDS = {"recall", "search_library", "library_search", "search_repos",
                 "from_library", "library"}
_REPO_WORDS = {"learn_repo", "study_repo", "read_repo", "fetch_repo",
               "ingest_repo", "learn", "add_repo", "load_repo"}


def _json_objects(text: str):
    dec = json.JSONDecoder()
    i = 0
    while True:
        i = text.find("{", i)
        if i < 0:
            return
        try:
            obj, end = dec.raw_decode(text, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict):
            yield obj
        i = max(end, i + 1)


def _first(d, *keys, default=""):
    for k in keys:
        if isinstance(d, dict) and d.get(k):
            return d[k]
    return default


def parse_tool_call(text: str) -> dict | None:
    """Recognise Anya asking to search her library or read a repo."""
    for obj in _json_objects(text or ""):
        name = _first(obj, "name", "tool", "action", "function")
        if not isinstance(name, str) or not name.strip():
            continue
        key = name.strip().lower()
        args = _first(obj, "arguments", "args", "params", "parameters", default=None)
        if not isinstance(args, dict):
            args = {}
        merged = {**obj, **args}
        if key in _REPO_WORDS:
            repo = _first(merged, "repo", "repository", "url", "source", "project")
            if repo:
                return {"name": "learn_repo", "repo": str(repo)}
        if key in _RECALL_WORDS:
            query = _first(merged, "query", "q", "about", "topic", "text", "search")
            return {"name": "recall", "query": str(query)}
    return None
