"""Projects: a sandboxed workspace where Anya builds things on this PC.

Anya can create a project, write real files into it, keep a task list, and run
an allow-listed build command (Gradle, javac, adb, git, python) to produce a
genuine, installable APK.  Everything she writes stays inside one workspace
folder; a write that reaches outside it is *not* applied — it becomes a pending
request the user approves or denies in the GUI.

This module is deliberately stdlib-only and has no dependency on anya_ui, in the
same spirit as web.py.

Public surface
--------------
    configure(state_dir, workspace)  point the module at its folders
    root() / set_root(path)          the workspace folder (default S:\\anya-projects)
    list_projects()                  summaries, newest first
    get_project(pid)                 one project: manifest + files + build info
    new_project(name, kind, ...)     create a folder (+ Android scaffold)
    delete_project(pid)              remove a project *she* created (never outside root)
    reveal(pid)                      open the project folder in the file manager
    add_task(pid, title, status)     add/update a task
    set_task(pid, task_id, status)   move a task between todo/doing/done
    write_file(pid, path, content)   write inside the project (else raises OutsideWrite)
    read_file(pid, path)             read a file from the project
    list_files(pid)                  relative paths a UI can show
    run(pid, command, timeout)       run one allow-listed command, capture output
    build_apk(pid)                   run `gradlew assembleDebug`, return the APK
    new_project_name(text)           "make an app called X" -> "X", else None
    wants_build(text)                "build the apk" -> True
    parse_tool_call(text)            a {"name": ...} JSON tool call -> an action
    plan(pid)                        the task list, ready for the UI/status
    current() / set_current(pid)     the project being worked on
    activity() / feed()              what Anya is doing *right now*

Everything here is bounded on purpose: file reads/writes are capped, command
output is capped, and commands have a timeout.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path

# --- bounds -----------------------------------------------------------------
MAX_WRITE_BYTES = 2_000_000        # a single file Anya writes
MAX_READ_CHARS = 40_000            # returned to the UI / to her
MAX_LIST = 400                     # entries listed per project
MAX_LOG = 200                      # manifest activity entries kept
CMD_OUT_CHARS = 6_000              # tail of command output handed back to her
BUILD_TIMEOUT = 1_800              # a first Gradle build can take minutes
DEFAULT_TIMEOUT = 600
SKIP_DIRS = {"build", ".gradle", ".idea", ".git", ".anya", "node_modules", "__pycache__"}
SKIP_FILES = {"project.json"}
HIDDEN_PREFIX = (".", "_")         # workspace bookkeeping (e.g. _template, _smoke)

ANDROID_KIND = "android"


class ProjectError(Exception):
    """Something went wrong that is worth telling the user about."""


class OutsideWrite(ProjectError):
    """A write landed outside the workspace and needs the user to approve it."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(reason)
        self.path = path
        self.reason = reason


# --- configuration ----------------------------------------------------------

_STATE_DIR: Path | None = None     # where approvals.json lives (anya-ui)
_ROOT: Path = Path(r"S:\anya-projects")
_TEMPLATES: Path = Path(r"S:\anya-projects\_template")
_CURRENT: str = ""                 # the project id the UI is focused on
_ACTIVITY: dict = {"what": "", "detail": "", "project": "", "ts": 0.0}
_FEED: list[dict] = []


def configure(state_dir, workspace=None, templates=None) -> None:
    """Point the module at its folders.  Called once at start-up."""
    global _STATE_DIR, _TEMPLATES, _CURRENT
    _STATE_DIR = Path(state_dir)
    if workspace:
        set_root(workspace)
    if templates:
        _TEMPLATES = Path(templates)
    _CURRENT = _read_current()


def _current_path() -> Path:
    d = _STATE_DIR or Path.cwd()
    return Path(d) / "current.txt"


def _read_current() -> str:
    """The project the UI focused on last time — so 'working on' survives a restart."""
    try:
        pid = (_STATE_DIR or Path.cwd()).joinpath("current.txt").read_text(
            encoding="utf-8").strip()
    except OSError:
        return ""
    if pid and (_ROOT / pid / "project.json").exists():
        return pid
    return ""


def root() -> Path:
    return _ROOT


def set_root(workspace) -> Path:
    global _ROOT, _TEMPLATES
    _ROOT = Path(workspace)
    _TEMPLATES = _ROOT / "_template"
    return _ROOT


def _ensure_root() -> Path:
    _ROOT.mkdir(parents=True, exist_ok=True)
    return _ROOT


# --- ids and paths ----------------------------------------------------------

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def slugify(name: str) -> str:
    """A safe folder name from a human title ("Hello Anya!" -> "hello-anya")."""
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)[:40].strip("-")
    return s or "project"


def _project_dir(pid: str) -> Path:
    if not _ID_RE.match(pid or "") or ".." in pid:
        raise ProjectError(f"bad project id: {pid!r}")
    return _ROOT / pid


def _manifest_path(pid: str) -> Path:
    return _project_dir(pid) / "project.json"


def _safe_rel(rel: str) -> Path:
    """A relative path that cannot escape its project folder."""
    raw = (rel or "").strip().replace("\\", "/")
    if not raw:
        raise ProjectError("empty path")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ProjectError(f"paths must be relative to the project: {rel!r}")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ProjectError(f"paths may not contain '..': {rel!r}")
    return Path(*parts)


def _inside(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


# --- manifests --------------------------------------------------------------

def _load(pid: str) -> dict:
    mp = _manifest_path(pid)
    if not mp.exists():
        raise ProjectError(f"no such project: {pid}")
    try:
        return json.loads(mp.read_text(encoding="utf-8"))
    except Exception as exc:                                      # noqa: BLE001
        raise ProjectError(f"project.json unreadable: {exc}") from exc


def _save(pid: str, proj: dict) -> None:
    proj["updated"] = time.time()
    proj["log"] = proj.get("log", [])[-MAX_LOG:]
    _manifest_path(pid).write_text(json.dumps(proj, indent=2), encoding="utf-8")


def _log(pid: str, kind: str, text: str) -> None:
    """Append one line to the project's activity log and the live feed."""
    try:
        proj = _load(pid)
        proj.setdefault("log", []).append({"ts": time.time(), "kind": kind, "text": text})
        _save(pid, proj)
    except ProjectError:
        pass
    _FEED.append({"ts": time.time(), "kind": kind, "text": text, "project": pid})
    del _FEED[:-40]


def _note(what: str, detail: str = "", pid: str = "") -> None:
    """Set the 'working on now' line the GUI shows in the header of Projects."""
    _ACTIVITY.update(what=what, detail=detail, project=pid or _ACTIVITY.get("project", ""),
                     ts=time.time())


def activity() -> dict:
    return dict(_ACTIVITY)


def feed() -> list[dict]:
    return list(_FEED)[-20:]


# --- project lifecycle ------------------------------------------------------

def list_projects() -> list[dict]:
    _ensure_root()
    out: list[dict] = []
    for child in sorted(_ROOT.iterdir()):
        if not child.is_dir() or child.name.startswith(HIDDEN_PREFIX):
            continue
        mp = child / "project.json"
        if not mp.exists():
            continue
        try:
            proj = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:                                         # noqa: BLE001
            continue
        out.append(_summary(proj))
    out.sort(key=lambda p: p.get("updated", 0), reverse=True)
    return out


def _summary(proj: dict) -> dict:
    tasks = proj.get("tasks", [])
    counts = {"todo": 0, "doing": 0, "done": 0}
    for t in tasks:
        counts[t.get("status", "todo")] = counts.get(t.get("status", "todo"), 0) + 1
    return {
        "id": proj.get("id", ""),
        "name": proj.get("name", ""),
        "kind": proj.get("kind", ""),
        "description": proj.get("description", ""),
        "status": proj.get("status", "active"),
        "created": proj.get("created", 0),
        "updated": proj.get("updated", 0),
        "task_counts": counts,
        "task_total": len(tasks),
        "last_build": proj.get("last_build") or {},
        "path": str(_project_dir(proj.get("id", ""))),
        "current": proj.get("id") == _CURRENT,
    }


def get_project(pid: str) -> dict:
    proj = _load(pid)
    full = dict(proj)
    full["files"] = list_files(pid)
    full["feed"] = [e for e in _FEED if e.get("project") == pid][-15:]
    full["path"] = str(_project_dir(pid))
    full["current"] = pid == _CURRENT
    full["apk"] = _find_apk(pid)
    full["can_build"] = (Path(_project_dir(pid)) / "gradlew.bat").exists()
    return full


def new_project(name: str, kind: str = ANDROID_KIND, description: str = "") -> dict:
    """Create a project folder.  Android projects come with a ready scaffold."""
    name = (name or "").strip()[:60] or "New project"
    _ensure_root()
    pid = slugify(name)
    base = _ROOT / pid
    n = 2
    while base.exists():
        pid = f"{slugify(name)}-{n}"
        base = _ROOT / pid
        n += 1

    _note("Creating project", name, pid)
    if kind == ANDROID_KIND:
        _scaffold_android(pid, name)
    else:
        base.mkdir(parents=True, exist_ok=True)

    now = time.time()
    proj = {
        "id": pid, "name": name, "kind": kind, "description": description,
        "created": now, "updated": now, "status": "active",
        "tasks": [{"id": "t1", "title": f"Set up {name}", "status": "done",
                   "created": now, "updated": now}],
        "log": [], "last_build": {},
    }
    proj["log"].append({"ts": now, "kind": "note", "text": f"Created the {kind} project"})
    _save(pid, proj)
    README = base / "README.md"
    if not README.exists():
        README.write_text(
            f"# {name}\n\nCreated by Anya on {time.strftime('%Y-%m-%d %H:%M')}.\n\n"
            f"Kind: {kind}\n\n{description}\n", encoding="utf-8")
    set_current(pid)
    _note("Created project", name, pid)
    return get_project(pid)


def delete_project(pid: str) -> None:
    d = _project_dir(pid)
    if not _inside(_ROOT, d) or d == _ROOT:
        raise ProjectError("refusing to delete outside the workspace")
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    if _CURRENT == pid:
        set_current("")


def reveal(pid: str) -> str:
    """Open a project's folder in the desktop file manager.

    The path is derived from the project id inside the workspace, so there is
    nothing here for a stray request to point somewhere else. Returns the path.
    """
    d = _project_dir(pid)
    if not _inside(_ROOT, d) or d == _ROOT:
        raise ProjectError("refusing to open outside the workspace")
    if not d.exists():
        raise ProjectError(f"there is no folder for {pid}")
    try:
        if hasattr(os, "startfile"):                  # Windows Explorer
            os.startfile(str(d))                      # noqa: S606
        else:                                         # the other two desktops
            subprocess.Popen(["open" if os.uname().sysname == "Darwin" else "xdg-open",
                              str(d)])                    # noqa: S603,S607
    except OSError as exc:
        raise ProjectError(f"couldn't open the folder: {exc}") from exc
    return str(d)


def current() -> str:
    return _CURRENT


def set_current(pid: str) -> None:
    global _CURRENT
    _CURRENT = pid or ""
    if pid:
        _ACTIVITY["project"] = pid
    try:
        d = _STATE_DIR or Path.cwd()
        (Path(d) / "current.txt").write_text(_CURRENT, encoding="utf-8")
    except OSError:
        pass


# --- tasks ------------------------------------------------------------------

def add_task(pid: str, title: str, status: str = "todo") -> dict:
    proj = _load(pid)
    now = time.time()
    title = (title or "").strip()[:160] or "Untitled task"
    tid = f"t{int(now * 1000) % 10_000_000}"
    proj.setdefault("tasks", []).append(
        {"id": tid, "title": title, "status": _norm_status(status),
         "created": now, "updated": now})
    _save(pid, proj)
    _log(pid, "task", f"Added task: {title}")
    return get_project(pid)


def set_task(pid: str, task_id: str, status: str) -> dict:
    proj = _load(pid)
    for t in proj.setdefault("tasks", []):
        if t.get("id") == task_id:
            t["status"] = _norm_status(status)
            t["updated"] = time.time()
            _log(pid, "task", f"{t['status']}: {t.get('title', '')}")
            break
    _save(pid, proj)
    return get_project(pid)


def _norm_status(s: str) -> str:
    s = (s or "").strip().lower()
    return {"doing": "doing", "in_progress": "doing", "in-progress": "doing",
            "active": "doing", "started": "doing", "done": "done", "complete": "done",
            "completed": "done", "finished": "done"}.get(s, "todo")


def plan(pid: str) -> list[dict]:
    """The task list alone — cheap enough to put in /api/status every 5s."""
    try:
        return _load(pid).get("tasks", [])
    except ProjectError:
        return []


# --- files ------------------------------------------------------------------

def write_file(pid: str, rel: str, content: str) -> dict:
    """Write a file inside the project.  Outside the workspace -> OutsideWrite."""
    if content is None:
        content = ""
    if len(content.encode("utf-8", "ignore")) > MAX_WRITE_BYTES:
        raise ProjectError(f"file too big to write ({len(content)} chars)")

    rel_path = _safe_rel(rel)
    base = _project_dir(pid)
    if not base.exists():
        raise ProjectError(f"no such project: {pid}")
    target = base / rel_path

    if not _inside(base, target):
        raise OutsideWrite(str(target), "path left the project folder")

    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    target.write_text(content, encoding="utf-8")
    proj = _load(pid)
    proj["updated"] = time.time()
    _save(pid, proj)
    _note("Writing a file", rel, pid)
    _log(pid, "file", ("Updated " if existed else "Created ") + rel)
    return {"project": pid, "path": rel, "bytes": len(content.encode('utf-8')),
            "created": not existed}


def read_file(pid: str, rel: str, max_chars: int = MAX_READ_CHARS) -> dict:
    base = _project_dir(pid)
    target = base / _safe_rel(rel)
    if not _inside(base, target):
        raise ProjectError("path left the project folder")
    if not target.exists():
        raise ProjectError(f"no such file: {rel}")
    if target.is_dir():
        raise ProjectError(f"{rel} is a folder")
    text = target.read_text(encoding="utf-8", errors="replace")
    cut = len(text) > max_chars
    return {"project": pid, "path": rel, "text": text[:max_chars],
            "truncated": cut, "bytes": target.stat().st_size}


def list_files(pid: str, limit: int = MAX_LIST) -> list[dict]:
    base = _project_dir(pid)
    if not base.exists():
        raise ProjectError(f"no such project: {pid}")
    out: list[dict] = []
    for p in sorted(base.rglob("*")):
        rel = p.relative_to(base)
        if any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts):
            continue
        if rel.name in SKIP_FILES:
            continue
        if p.is_dir():
            continue
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        out.append({"path": str(rel).replace("\\", "/"), "bytes": size})
        if len(out) >= limit:
            break
    return out


def _find_apk(pid: str) -> dict:
    base = _project_dir(pid)
    out = base / "app" / "build" / "outputs" / "apk" / "debug"
    if not out.exists():
        return {}
    apks = sorted(out.glob("*.apk"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not apks:
        return {}
    a = apks[0]
    return {"path": str(a), "name": a.name, "bytes": a.stat().st_size,
            "built": a.stat().st_mtime}


# --- the Android scaffold ---------------------------------------------------

def _template_dir() -> Path | None:
    cand = _TEMPLATES / ANDROID_KIND
    if cand.exists():
        return cand
    # fall back to the stock Android Studio project, if it is still around
    guess = Path(os.environ.get("USERPROFILE", "")) / "AndroidStudioProjects" / "MyApplication"
    if guess.exists():
        return guess
    return None


def _scaffold_android(pid: str, name: str) -> None:
    """Copy the template, then rewrite the app id and package for this project."""
    src = _template_dir()
    if src is None:
        raise ProjectError(
            "no Android template found - expected a scaffold at "
            f"{_TEMPLATES / ANDROID_KIND}")
    dst = _ROOT / pid
    ignore = shutil.ignore_patterns("build", ".gradle", ".idea", ".git", "local.properties")
    shutil.copytree(src, dst, ignore=ignore, dirs_exist_ok=False)
    _patch_android(dst, pid, name)
    sdk = find_sdk()
    if sdk:
        (dst / "local.properties").write_text(
            "sdk.dir=" + str(sdk).replace("\\", "\\\\") + "\n", encoding="utf-8")


def _patch_android(dst: Path, pid: str, name: str) -> None:
    pkg = "com.anya." + re.sub(r"[^a-z0-9]", "", pid)[:24]
    root_slug = re.sub(r"[^a-z0-9]", "", pid)[:24]

    sg = dst / "settings.gradle.kts"
    if sg.exists():
        sg.write_text(re.sub(r'rootProject\.name\s*=\s*"[^"]*"',
                             f'rootProject.name = "{root_slug}"',
                             sg.read_text(encoding="utf-8")), encoding="utf-8")

    bg = dst / "app" / "build.gradle.kts"
    if bg.exists():
        txt = bg.read_text(encoding="utf-8")
        txt = txt.replace('namespace = "com.example.myapplication"', f'namespace = "{pkg}"')
        txt = txt.replace('applicationId = "com.example.myapplication"', f'applicationId = "{pkg}"')
        bg.write_text(txt, encoding="utf-8")

    strings = dst / "app" / "src" / "main" / "res" / "values" / "strings.xml"
    if strings.exists():
        strings.write_text(re.sub(r"<string name=\"app_name\">.*?</string>",
                                  f'<string name="app_name">{_xml(name)}</string>',
                                  strings.read_text(encoding="utf-8")), encoding="utf-8")

    for srcset in ("main", "test", "androidTest"):
        old = dst / "app" / "src" / srcset / "java" / "com" / "example" / "myapplication"
        new = dst / "app" / "src" / srcset / "java" / Path(*pkg.split("."))
        if old.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(new))
    for base in (dst / "app" / "src",):
        for kt in base.rglob("*.kt"):
            txt = kt.read_text(encoding="utf-8").replace("com.example.myapplication", pkg)
            # make the starter screen say this app's own name, so a fresh project
            # is visibly its own the moment it is built and installed
            txt = txt.replace('name = "Android"', f'name = "{_kt(name)}"')
            txt = txt.replace('Greeting("Android")', f'Greeting("{_kt(name)}")')
            kt.write_text(txt, encoding="utf-8")


def _kt(s: str) -> str:
    """Escape a value for a Kotlin string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")


def _xml(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


# --- running commands -------------------------------------------------------

# Only these programs may be run, and only from inside a project folder.
ALLOWED = {
    "gradlew", "gradlew.bat", "gradle", "java", "javac", "kotlinc",
    "python", "python3", "py", "git", "adb", "aapt2", "apksigner",
    "zipalign", "d8", "keytool", "sdkmanager",
}
GIT_OK = {"init", "add", "commit", "status", "log", "diff", "branch", "checkout",
          "clone", "remote", "config", "ls-files", "rev-parse", "show"}
_SHELLY = re.compile(r"[\0;&|<>^`$]|\brm\b|\bdel\b|\brd\b|\bformat\b")


def find_sdk() -> Path | None:
    for c in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"),
              Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk",
              Path(r"C:\Android\Sdk"), Path(r"S:\Android\Sdk")):
        if c and Path(c).exists():
            return Path(c)
    return None


def find_jbr() -> Path | None:
    for c in (os.environ.get("JAVA_HOME"),
              Path(r"C:\Program Files\Android\Android Studio\jbr"),
              Path(r"C:\Program Files\Java")):
        if c and Path(c).exists():
            return Path(c)
    return None


def _which(exe: str) -> str | None:
    found = shutil.which(exe)
    if found:
        return found
    jbr = find_jbr()
    if jbr and (jbr / "bin").exists():
        for n in (exe, exe + ".exe"):
            p = jbr / "bin" / n
            if p.exists():
                return str(p)
    sdk = find_sdk()
    if sdk:
        for pat in (f"build-tools/*/{exe}.exe", f"platform-tools/{exe}.exe",
                    f"cmdline-tools/*/bin/{exe}.bat", f"emulator/{exe}.exe"):
            hits = sorted(sdk.glob(pat))
            if hits:
                return str(pat if False else hits[-1])
    return None


def _env() -> dict:
    """A build environment for the child process only (never mutates ours).

    Gives Gradle the Android Studio JDK, points tools at the Android SDK, and
    puts build-tools / platform-tools on PATH so adb, aapt2 and zipalign resolve.
    """
    env = dict(os.environ)
    jbr, sdk = find_jbr(), find_sdk()
    extra: list[str] = []
    if jbr:
        env["JAVA_HOME"] = str(jbr)
        if (jbr / "bin").exists():
            extra.append(str(jbr / "bin"))
    if sdk:
        env["ANDROID_HOME"] = str(sdk)
        env["ANDROID_SDK_ROOT"] = str(sdk)
        extra.append(str(sdk / "platform-tools"))
        extra.append(str(sdk / "emulator"))
        extra.append(str(sdk / "cmdline-tools" / "latest" / "bin"))
        bt = sdk / "build-tools"
        if bt.exists():
            vers = sorted((d for d in bt.iterdir() if d.is_dir()), key=lambda d: d.name)
            if vers:
                extra.insert(0, str(vers[-1]))
    env["PATH"] = os.pathsep.join([p for p in extra if Path(p).exists()] +
                                  [env.get("PATH", "")])
    env.setdefault("GRADLE_USER_HOME", str(Path.home() / ".gradle"))
    return env


def _argv(command: str) -> list[str]:
    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        raise ProjectError(f"could not read that command: {exc}") from exc
    return [p.strip('"').strip("'") for p in parts if p.strip()]


def run(pid: str, command: str, timeout: int = DEFAULT_TIMEOUT, on_line=None) -> dict:
    """Run one allow-listed command inside the project folder.

    `on_line` (if given) is called with each line of output as it arrives, so a
    long Gradle build can be watched live.  Returns the tail of the output.
    """
    base = _project_dir(pid)
    if not base.exists():
        raise ProjectError(f"no such project: {pid}")
    argv = _argv(command)
    if not argv:
        raise ProjectError("empty command")
    exe = argv[0].lower().lstrip("./\\")
    if exe not in ALLOWED:
        raise ProjectError(
            f"'{argv[0]}' is not on the allowed list ({', '.join(sorted(ALLOWED))})")
    if _SHELLY.search(command):
        raise ProjectError("that command contains shell metacharacters; keep it simple")
    if exe in ("git",) and (len(argv) < 2 or argv[1].lower() not in GIT_OK):
        raise ProjectError(f"git {' '.join(argv[1:2]) or '(none)'} is not allowed here")

    if exe.startswith("gradlew"):
        gw = base / "gradlew.bat"
        if not gw.exists():
            raise ProjectError("this project has no Gradle wrapper to run")
        argv[0] = str(gw)

    _note("Running a command", " ".join(argv[:3]), pid)
    _log(pid, "command", " ".join(argv))
    env = _env()
    t0 = time.time()
    try:
        if on_line is None:
            proc = subprocess.run(argv, cwd=str(base), env=env, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace",
                                  timeout=timeout, creationflags=0x08000000)
            code = proc.returncode
            out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        else:
            code, out = _run_streaming(argv, base, env, timeout, on_line)
    except subprocess.TimeoutExpired:
        code, out = -1, f"(command timed out after {timeout}s)"
    except FileNotFoundError as exc:
        raise ProjectError(f"could not find '{argv[0]}': {exc}") from exc
    dur = round(time.time() - t0, 1)

    log_path = base / ".anya"
    log_path.mkdir(exist_ok=True)
    (log_path / "last-command.log").write_text(f"$ {' '.join(argv)}\n\n{out}",
                                               encoding="utf-8", errors="replace")
    tail = out[-CMD_OUT_CHARS:] if len(out) > CMD_OUT_CHARS else out
    ok = code == 0
    _log(pid, "command", f"exit {code} in {dur}s")
    _note("Finished a command", f"exit {code}", pid)
    return {"project": pid, "cmd": " ".join(argv), "code": code, "ok": ok,
            "output": tail, "truncated": len(out) > CMD_OUT_CHARS,
            "duration_s": dur}


def _run_streaming(argv: list, base: Path, env: dict, timeout: int, on_line) -> tuple:
    """Run a child process, handing each output line to `on_line` as it arrives."""
    proc = subprocess.Popen(argv, cwd=str(base), env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", creationflags=0x08000000)
    chunks: list[str] = []
    timed_out = {"hit": False}

    def _kill() -> None:
        timed_out["hit"] = True
        try:
            proc.kill()
        except Exception:                                         # noqa: BLE001
            pass

    killer = threading.Timer(timeout, _kill)
    killer.start()
    try:
        for line in proc.stdout:                                  # type: ignore[union-attr]
            chunks.append(line)
            if len(chunks) > 20000:
                del chunks[:10000]
            try:
                on_line(line.rstrip("\r\n"))
            except Exception:                                     # noqa: BLE001
                pass
        code = proc.wait()
    finally:
        killer.cancel()
    out = "".join(chunks)
    if timed_out["hit"]:
        out += f"\n(command timed out after {timeout}s)"
        code = -1
    return code, out


def build_apk(pid: str, on_line=None) -> dict:
    """Assemble a debug APK for an Android project and return its path.

    `on_line` streams the build log line by line, for the GUI's build view.
    """
    proj = _load(pid)
    if proj.get("kind") != ANDROID_KIND:
        raise ProjectError("only Android projects can build an APK")
    _note("Building the APK", proj.get("name", pid), pid)
    res = run(pid, "gradlew assembleDebug", timeout=BUILD_TIMEOUT, on_line=on_line)
    apk = _find_apk(pid)
    out = {"project": pid, "ok": bool(res["ok"] and apk), "code": res["code"],
           "apk": apk, "output": res["output"], "duration_s": res["duration_s"]}
    proj = _load(pid)
    proj["last_build"] = {"ok": out["ok"], "ts": time.time(), "code": res["code"],
                          "apk": apk.get("path", ""), "name": apk.get("name", ""),
                          "bytes": apk.get("bytes", 0)}
    _save(pid, proj)
    if out["ok"]:
        _log(pid, "build", f"Built {apk.get('name', 'APK')}")
        _note("APK built", apk.get("name", ""), pid)
    else:
        _log(pid, "build", f"Build failed (exit {res['code']})")
        _note("Build failed", f"exit {res['code']}", pid)
    return out


# --- approvals (writes outside the workspace) -------------------------------

def _approvals_path() -> Path:
    d = _STATE_DIR or Path.cwd()
    return Path(d) / "approvals.json"


def _load_approvals() -> list[dict]:
    p = _approvals_path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                             # noqa: BLE001
        return []


def _save_approvals(items: list[dict]) -> None:
    _approvals_path().write_text(json.dumps(items, indent=2), encoding="utf-8")


def request_write(path: str, content: str, reason: str = "") -> dict:
    """Queue a write outside the workspace for the user to approve."""
    aid = f"a{int(time.time() * 1000) % 10_000_000}"
    item = {"id": aid, "path": str(path), "bytes": len((content or "").encode("utf-8")),
            "reason": reason or "outside the project workspace",
            "created": time.time(), "content": content or "",
            "preview": (content or "")[:400]}
    items = _load_approvals()
    items.append(item)
    _save_approvals(items)
    _note("Waiting for approval", str(path))
    _FEED.append({"ts": time.time(), "kind": "approval", "text": f"Approve write to {path}",
                  "project": ""})
    return {k: v for k, v in item.items() if k != "content"}


def list_approvals() -> list[dict]:
    return [{k: v for k, v in it.items() if k != "content"}
            for it in _load_approvals()]


def resolve_approval(aid: str, approve: bool) -> dict:
    items = _load_approvals()
    keep, found = [], None
    for it in items:
        if it.get("id") == aid:
            found = it
        else:
            keep.append(it)
    _save_approvals(keep)
    if not found:
        raise ProjectError(f"no such approval: {aid}")
    if not approve:
        return {"ok": True, "approved": False, "path": found["path"]}
    target = Path(found["path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(found.get("content", ""), encoding="utf-8")
    _note("Applied approved write", str(target))
    return {"ok": True, "approved": True, "path": str(target),
            "bytes": target.stat().st_size}


def write_or_request(pid: str, rel: str, content: str) -> dict:
    """Write inside the project, or queue it for approval if it points outside.

    A `..` traversal is refused outright (it is only ever suspicious); an
    absolute path outside the workspace becomes a pending approval instead.
    """
    raw = (rel or "").strip()
    if not raw:
        raise ProjectError("empty path")
    parts = re.split(r"[\\/]", raw)
    if any(p == ".." for p in parts):
        raise ProjectError(f"paths may not contain '..': {rel!r}")
    absolute = bool(re.match(r"^[A-Za-z]:", rel)) or rel.replace("\\", "/").startswith("/")
    if absolute:
        target = Path(rel)
        if _inside(_project_dir(pid), target):
            return write_file(pid, str(target.relative_to(_project_dir(pid))), content)
        req = request_write(str(target), content, "outside the project workspace")
        return {"project": pid, "path": str(target), "pending": True, "approval": req}
    try:
        return write_file(pid, rel, content)
    except OutsideWrite as exc:
        req = request_write(exc.path, content, str(exc))
        return {"project": pid, "path": exc.path, "pending": True, "approval": req}


# --- reading the user's intent ----------------------------------------------

_NEW_PROJECT_RE = re.compile(
    r"(?i)\b(?:create|make|start|begin|set\s?up|build|want)\s+(?:me\s+)?"
    r"(?:a\s+|an\s+|the\s+)?(?:\w+\s+){0,3}?(?:app|application|project|game)\b"
    r"[^.\n]{0,40}?\b(?:called|named)\s+[\"']?([A-Za-z0-9][A-Za-z0-9 _-]{1,40})")
_BUILD_RE = re.compile(
    r"(?i)\b(?:build|compile|assemble|package|make)\b[^.\n]{0,25}\b(?:apk|app|project)\b"
    r"|\b(?:build|make)\s+(?:me\s+)?an?\s+apk\b"
    r"|\b(?:build|compile|assemble|package|make)\s+(?:it|this|that|them)\b")


def new_project_name(text: str) -> str | None:
    m = _NEW_PROJECT_RE.search(text or "")
    if not m:
        return None
    return _clean_name(m.group(1))


def _clean_name(s: str) -> str:
    """Trim a captured project name down to the name itself.

    "Hello Anya please" -> "Hello Anya"; "Notes and build it" -> "Notes".
    """
    s = s.strip(" \t\"'.,;:!?")
    s = re.split(r"(?i)\s+(?:and|then|so|that|which|to|please|for)\b", s)[0]
    s = re.sub(r"(?i)\s+(?:please|now|thanks|thank you|ok|okay|for me)$", "", s)
    return re.sub(r"\s+", " ", s).strip(" \t\"'.,;:!?")[:40]


def wants_build(text: str) -> bool:
    return bool(_BUILD_RE.search(text or ""))


# --- the tool protocol ------------------------------------------------------

_WRITE_WORDS = {"write_file", "writefile", "write", "create_file", "createfile",
                "save_file", "savefile", "edit_file", "put_file"}
_NEW_WORDS = {"new_project", "newproject", "create_project", "createproject",
              "make_project", "project_new", "start_project"}
_TASK_WORDS = {"project_task", "projecttask", "task", "add_task", "addtask",
               "update_task", "set_task", "update_progress", "plan"}
_BUILD_WORDS = {"build_apk", "buildapk", "build", "make_apk", "makeapk",
                "assemble", "compile"}
_RUN_WORDS = {"run_command", "runcommand", "run", "exec", "execute", "shell", "command"}
_LIST_WORDS = {"list_files", "listfiles", "ls", "files", "list_project"}
_READ_WORDS = {"read_file", "readfile", "read", "cat", "open_file", "openfile"}
# Autopilot's "I am done" marker. Recognised so the streaming filter swallows it
# like any other tool call rather than printing JSON into the log.
_DONE_WORDS = {"finish", "finished", "done", "complete", "completed", "stop"}


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


def _first(d: dict, *keys, default=""):
    for k in keys:
        if isinstance(d, dict) and d.get(k):
            return d[k]
    return default


def parse_tool_call(text: str) -> dict | None:
    """Recognise one of Anya's project tool calls and turn it into an action.

    Tolerant of the same key drift web.parse_tool_call allows: name/tool/action,
    arguments/args/params, and flat keys.
    """
    for obj in _json_objects(text or ""):
        name = _first(obj, "name", "tool", "action", "function")
        if not isinstance(name, str) or not name.strip():
            continue
        key = name.strip().lower()
        args = _first(obj, "arguments", "args", "params", "parameters", default=None)
        if not isinstance(args, dict):
            args = {}
        merged = {**obj, **args}          # flat keys lose to the arguments block

        if key in _DONE_WORDS:
            return {"name": "finish", "project": str(_first(merged, "project", "id"))}

        if key in _NEW_WORDS:
            # the tool itself is called "name", so read the project name from the
            # arguments block and only fall back to the top level afterwards.
            nm = _first(args, "project_name", "name", "title", "project") \
                or _first(obj, "project_name", "title", "project")
            kind = str(_first(merged, "kind", default="android")).lower()
            if nm:
                return {"name": "new_project", "project_name": str(nm),
                        "kind": "android" if "android" in kind else "generic"}

        if key in _WRITE_WORDS:
            rel = _first(merged, "path", "file", "filename", "filepath")
            content = merged.get("content", merged.get("text", merged.get("code", "")))
            if rel:
                return {"name": "write_file", "project": str(_first(merged, "project", "id")),
                        "path": str(rel), "content": str(content)}

        if key in _TASK_WORDS:
            title = _first(merged, "title", "task", "text", "description", "summary")
            status = _first(merged, "status", "state", "as", default="todo")
            if title or status:
                return {"name": "project_task", "project": str(_first(merged, "project", "id")),
                        "title": str(title), "status": str(status)}

        if key in _BUILD_WORDS:
            return {"name": "build_apk", "project": str(_first(merged, "project", "id"))}

        if key in _RUN_WORDS:
            cmd = _first(merged, "command", "cmd", "run")
            if isinstance(cmd, list):
                cmd = " ".join(str(c) for c in cmd)
            if cmd:
                return {"name": "run_command", "project": str(_first(merged, "project", "id")),
                        "command": str(cmd)}

        if key in _LIST_WORDS:
            return {"name": "list_files", "project": str(_first(merged, "project", "id"))}

        if key in _READ_WORDS:
            rel = _first(merged, "path", "file", "filename")
            if rel:
                return {"name": "read_file", "project": str(_first(merged, "project", "id")),
                        "path": str(rel)}
    return None


# --- convenience for callers -------------------------------------------------

def summary_for_status(pid: str | None = None) -> dict:
    """A compact block for /api/status so the GUI updates on its normal poll."""
    pid = pid or _CURRENT
    if not pid:
        projects = list_projects()
        pid = projects[0]["id"] if projects else ""
    block: dict = {"id": pid, "activity": activity(), "feed": feed()[-8:],
                   "count": len(list_projects())}
    if pid:
        try:
            proj = _load(pid)
            s = _summary(proj)
            block.update(name=s["name"], kind=s["kind"], status=s["status"],
                         tasks=proj.get("tasks", []), task_counts=s["task_counts"],
                         last_build=s["last_build"])
        except ProjectError:
            pass
    return block
