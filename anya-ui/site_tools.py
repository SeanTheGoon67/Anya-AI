from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent


class SiteError(Exception):
    pass


def _cfg_get(cfg: dict, key: str, default: Any = "") -> Any:
    v = cfg.get(key, default)
    return v if v not in (None, "") else default


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=timeout, shell=False)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        raise SiteError("command timed out")
    except Exception as exc:
        raise SiteError(str(exc))


def is_gh_available(gh_path: str) -> bool:
    try:
        code, _, _ = run([gh_path, "--version"], timeout=10)
        return code == 0
    except Exception:
        return False


def site_dir(cfg: dict) -> Path:
    d = Path(_cfg_get(cfg, "site_dir", str(PROJECT / "site")))
    d.mkdir(parents=True, exist_ok=True)
    return d


def status(cfg: dict) -> dict:
    d = site_dir(cfg)
    md = d / "index.md"
    html = d / "index.html"
    repo = _cfg_get(cfg, "site_repo", "")
    branch = _cfg_get(cfg, "site_branch", "main")
    gh = _cfg_get(cfg, "gh_path", r"C:\\Users\\Administrator\\AppData\\Local\\Temp\\ghbin\\bin\\gh.exe")
    return {
        "enabled": bool(cfg.get("site_enabled", True)),
        "repo": repo,
        "branch": branch,
        "dir": str(d),
        "has_md": md.exists(),
        "has_html": html.exists(),
        "gh_available": is_gh_available(gh) if gh else False,
        "use_html": bool(cfg.get("site_use_html", True)),
    }


def read(cfg: dict) -> dict:
    d = site_dir(cfg)
    md = (d / "index.md").read_text(encoding="utf-8", errors="replace") if (d / "index.md").exists() else ""
    html = (d / "index.html").read_text(encoding="utf-8", errors="replace") if (d / "index.html").exists() else ""
    return {"md": md, "html": html}


def write(cfg: dict, md: str = "", html: str = "", build_html: bool = True) -> dict:
    d = site_dir(cfg)
    if md is not None:
        (d / "index.md").write_text(md, encoding="utf-8")
    if html is not None:
        (d / "index.html").write_text(html, encoding="utf-8")
    if build_html and bool(cfg.get("site_use_html", True)) and md is not None:
        try:
            import markdown  # type: ignore

            h = markdown.markdown(md, extensions=["fenced_code", "tables", "toc", "codehilite"])
            tpl = (
                "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" "
                "content=\"width=device-width,initial-scale=1\"><title>Anya</title><style>body{font-family:-apple-system,"
                "BlinkMacSystemFont,Segoe UI,Roboto,Arial,sans-serif;line-height:1.6;max-width:800px;margin:40px auto;"
                "padding:0 20px;color:#222}h1,h2,h3{color:#333}a{color:#0969da}pre{background:#f6f8fa;padding:12px;"
                "overflow:auto;border-radius:6px}code{font-family:ui-monospace,monospace;font-size:.9em}</style>"
                "</head><body>" + h + "</body></html>"
            )
            (d / "index.html").write_text(tpl, encoding="utf-8")
        except Exception:
            pass  # keep as-is
    return status(cfg)


def pull(cfg: dict) -> tuple[bool, str]:
    d = site_dir(cfg)
    branch = _cfg_get(cfg, "site_branch", "main")
    gh = _cfg_get(cfg, "gh_path", r"C:\\Users\\Administrator\\AppData\\Local\\Temp\\ghbin\\bin\\gh.exe")
    if is_gh_available(gh):
        code, out, err = run([gh, "repo", "sync"], cwd=d)
        if code != 0:
            return False, err or out
        return True, out
    code, out, err = run(["git", "pull", "origin", branch], cwd=d)
    if code != 0:
        return False, err or out
    return True, out


def push(cfg: dict, message: str = "Update site") -> tuple[bool, str]:
    d = site_dir(cfg)
    branch = _cfg_get(cfg, "site_branch", "main")
    gh = _cfg_get(cfg, "gh_path", r"C:\\Users\\Administrator\\AppData\\Local\\Temp\\ghbin\\bin\\gh.exe")
    if is_gh_available(gh):
        run(["git", "add", "."], cwd=d)
        run(["git", "commit", "-m", message or "Update site"], cwd=d)
        code, out, err = run([gh, "repo", "sync"], cwd=d)
        if code != 0:
            code, out, err = run(["git", "push", "origin", branch], cwd=d)
        if code != 0:
            return False, err or out
        return True, out
    run(["git", "add", "."], cwd=d)
    run(["git", "commit", "-m", message or "Update site"], cwd=d)
    code, out, err = run(["git", "push", "origin", branch], cwd=d)
    if code != 0:
        return False, err or out
    return True, out
