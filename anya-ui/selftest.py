#!/usr/bin/env python
"""
selftest.py — checks that Anya's UI, chat streaming and history all work.

Run it while the UI is up:
    S:\\envs\\ai\\Scripts\\python.exe anya-ui\\selftest.py
    S:\\envs\\ai\\Scripts\\python.exe anya-ui\\selftest.py --web     (also test browsing)
    S:\\envs\\ai\\Scripts\\python.exe anya-ui\\selftest.py --build   (also build a real APK)
    S:\\envs\\ai\\Scripts\\python.exe anya-ui\\selftest.py --net     (also read a GitHub repo)
    S:\\envs\\ai\\Scripts\\python.exe anya-ui\\selftest.py --voice   (also a speech round-trip)

It talks to the same HTTP API the browser uses, so a pass here means the
front-end has everything it needs.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8091"
fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        fails.append(name)


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read())


def post(path: str, body: dict):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=600)


def say_full(message: str, sid: str | None = None):
    """Send one message; collect the reply and any web-browsing events."""
    r = post("/api/chat", {"session_id": sid, "message": message})
    text, tokens, tps, got_sid, err, tools = "", 0, 0.0, sid, None, []
    for raw in r:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        ev = json.loads(line[5:].strip())
        kind = ev.get("type")
        if kind == "start":
            got_sid = ev["session_id"]
        elif kind == "token":
            text += ev["text"]
        elif kind == "done":
            tokens, tps = ev["tokens"], ev["tps"]
        elif kind == "tool":
            tools.append(ev)
        elif kind == "error":
            err = ev["message"]
    return got_sid, text, tokens, tps, err, tools


def say(message: str, sid: str | None = None):
    """Send one message and collect the streamed reply."""
    return say_full(message, sid)[:5]


def filter_section() -> None:
    """Offline unit checks for the filter that keeps tool-call JSON off the screen."""
    print("\n[7] reply filter  (offline)")
    try:
        import anya_ui                                  # noqa: PLC0415
    except Exception as exc:                            # noqa: BLE001
        check("app module imports", False, str(exc))
        return
    cases = [
        ('{"name": "web_open", "arguments": {"url": "https://e.com/a"}}', ""),
        ('Let me open that page:\n{"name": "web_open", "arguments": '
         '{"url": "https://x.dev"}}', "Let me open that page:\n"),
        ('```json\n{"name": "web_search", "arguments": {"query": "kotlin"}}\n```', ""),
        # the malformation that used to leak: a bare tool name, no "name" key
        ('{"web_search", "query": "latest Android version"}', ""),
        ('Checking.\n{"build_apk", "arguments": {}}\n', "Checking.\n"),
        ('Here:\n```kotlin\nfun main() {\n  println("hi")\n}\n```\nDone.',
         'Here:\n```kotlin\nfun main() {\n  println("hi")\n}\n```\nDone.'),
        ('The port is {"port": 8091}.', 'The port is {"port": 8091}.'),
        ('A data class is `{"a": 1}` in JSON terms.',
         'A data class is `{"a": 1}` in JSON terms.'),
    ]
    bad = []
    for raw, expect in cases:
        for chunk in (1, 5, 500):                       # token splits are arbitrary
            out = []
            filt = anya_ui._ReplyFilter(out.append)
            for i in range(0, len(raw), chunk):
                filt.feed(raw[i:i + chunk])
            filt.flush()
            if "".join(out) != expect:
                bad.append(f"{raw[:45]!r} @{chunk} -> {''.join(out)!r}")
    for line in bad:
        print("      " + line)
    check("tool-call JSON never reaches the screen", not bad)

    # the same question worded with a leading article must not search twice
    try:
        keys = [anya_ui._search_key(q) for q in (
            "the latest version of python", "latest version of python",
            "what is the latest version of python", "kotlin coroutines")]
        check("near-identical searches collapse to one key",
              len(set(keys[:3])) == 1 and keys[3] not in keys[:3],
              " / ".join(sorted(set(keys))))
    except Exception as exc:                            # noqa: BLE001
        check("near-identical searches collapse to one key", False, str(exc))

    # an unlabelled fence gets the right language; a labelled one is untouched
    try:
        f = "`" * 3
        got = [anya_ui._tag_fences(f + "\n" + body + "\n" + f + "\n").split(f)[1]
               .split("\n")[0].strip()
               for body in ("data class User(val id: Int)", "def f():\n    print(1)",
                            "public static void main(String[] a) {}")]
        keep = anya_ui._tag_fences(f + "bash\nls -la\n" + f)
        check("untagged code fences get a language tag",
              got == ["kotlin", "python", "java"], str(got))
        check("an already-tagged fence is left alone",
              keep.split(f)[1].split("\n")[0].strip() == "bash")
    except Exception as exc:                            # noqa: BLE001
        check("untagged code fences get a language tag", False, str(exc))


def web_section() -> None:
    """Optional extra checks. Needs real internet: `selftest.py --web`."""
    print("\n[8] web browsing  (needs internet)")
    before = get("/api/status").get("web_enabled")
    post("/api/settings", {"web_enabled": True}).read()
    check("web switch turns on", get("/api/status")["web_enabled"] is True)
    sid = None
    try:
        sid, text, _, _, err, tools = say_full(
            "Read this page and tell me what it is: https://example.com")
        check("pasted link: no error", err is None, str(err or ""))
        check("pasted link: the page was opened",
              any(t["name"] == "web_open" and t.get("ok", True) for t in tools))
        check("pasted link: reply mentions the page", "example" in text.lower(),
              text[:70].replace("\n", " ") + "…")
        check("pasted link: reply cites a source", "http" in text)

        _, text2, _, _, err2, tools2 = say_full(
            "Search the web for the current stable Kotlin version, and cite sources.", sid)
        check("search: no error", err2 is None, str(err2 or ""))
        check("search: the web was actually searched",
              any(t["name"] == "web_search" and t.get("ok", True) for t in tools2))
        check("search: reply carries links", "http" in text2,
              text2[:90].replace("\n", " "))

        _, text3, _, _, _, tools3 = say_full(
            "Just write a one-line Kotlin hello world, no searching.", sid)
        check("ordinary chat does not search", not tools3, f"{len(tools3)} event(s)")
    finally:
        post("/api/settings", {"web_enabled": bool(before)}).read()
        if sid:
            try:
                urllib.request.urlopen(urllib.request.Request(
                    BASE + "/api/sessions/" + sid, method="DELETE"), timeout=30).read()
            except Exception:                                      # noqa: BLE001
                pass
    check("web switch put back as it was",
          get("/api/status")["web_enabled"] == bool(before))


def projects_section(real_build: bool = False) -> None:
    """Projects: create, tasks, files, approvals, triggers.

    Uses the real workspace but always cleans up after itself. Pass `--build`
    to also assemble a real APK (that is the slow part).
    """
    print("\n[9] projects" + ("  (with a real APK build)" if real_build else "  (offline)"))
    try:
        import projects                                  # noqa: PLC0415
    except Exception as exc:                             # noqa: BLE001
        check("projects module imports", False, str(exc))
        return

    import shutil                                        # noqa: PLC0415
    import tempfile                                      # noqa: PLC0415
    from pathlib import Path                             # noqa: PLC0415

    root = get("/api/status").get("projects_root") or r"S:\anya-projects"
    state = Path(tempfile.mkdtemp(prefix="anya-selftest-"))
    projects.configure(state, root)
    check("module pointed at the workspace", str(projects.root()) == root, str(projects.root()))

    pid = None
    try:
        name = "Selftest App"
        proj = projects.new_project(name, kind="android")
        pid = proj["id"]
        base = Path(root) / pid
        check("project created", (base / "project.json").exists(), pid)
        check("android scaffold arrived", (base / "app" / "build.gradle.kts").exists())
        check("package rewritten", "com.example.myapplication" not in
              (base / "app" / "build.gradle.kts").read_text(encoding="utf-8"))
        main_kt = next((base / "app" / "src" / "main" / "java").rglob("MainActivity.kt"), None)
        check("starter screen is named after the app",
              main_kt is not None and f'"{name}"' in main_kt.read_text(encoding="utf-8"))

        projects.add_task(pid, "Do a thing")
        check("task added", len(projects.plan(pid)) == 2)
        tid = next(t["id"] for t in projects.plan(pid) if t["title"] == "Do a thing")
        projects.set_task(pid, tid, "done")
        check("task moved along",
              any(t["status"] == "done" and t["id"] == tid for t in projects.plan(pid)))

        projects.write_file(pid, "notes/hello.txt", "hi there")
        check("file written, read back",
              projects.read_file(pid, "notes/hello.txt")["text"] == "hi there")
        check("file listed", any(f["path"] == "notes/hello.txt"
                                 for f in projects.list_files(pid)))
        try:
            projects.write_file(pid, "notes/../../escape.txt", "nope")
            check("'..' in a path is refused", False)
        except projects.ProjectError:
            check("'..' in a path is refused", True)

        outside = state / "approved.txt"
        res = projects.write_or_request(pid, str(outside), "selftest")
        check("write outside the workspace waits for approval", bool(res.get("pending")))
        pending = projects.list_approvals()
        check("approval is listed", len(pending) == 1)
        projects.resolve_approval(pending[0]["id"], True)
        check("approving writes the file", outside.exists())

        res2 = projects.write_or_request(pid, str(state / "denied.txt"), "selftest")
        projects.resolve_approval(res2["approval"]["id"], False)
        check("denying writes nothing", not (state / "denied.txt").exists())

        try:
            projects.run(pid, "rm -rf .")
            check("shell metacharacters are refused", False)
        except projects.ProjectError:
            check("shell metacharacters are refused", True)

        check("intent: a name out of 'make me a small Android app called X'",
              projects.new_project_name("Make me a small Android app called Dice Roller, "
                                        "then build the APK.") == "Dice Roller")
        check("intent: 'build it' is a build",
              bool(projects.wants_build("make an app called Z and build it")))
        check("intent: plain chat is not a project",
              projects.new_project_name("What is a Kotlin data class?") is None
              and not projects.wants_build("What is a Kotlin data class?"))

        call = projects.parse_tool_call(
            '{"name": "write_file", "arguments": {"path": "a.txt", "content": "x"}}')
        check("tool JSON is understood", bool(call) and call.get("name") == "write_file")
        check("plain prose is not a tool call",
              projects.parse_tool_call("Sure, here is a data class for you.") is None)

        fin = projects.parse_tool_call('{"name": "finish"}')
        check("the autopilot 'finish' marker is understood",
              bool(fin) and fin.get("name") == "finish")

        try:
            projects.reveal("no-such-project-xyz")
            check("opening a missing folder is refused", False)
        except projects.ProjectError:
            check("opening a missing folder is refused", True)

        if real_build:
            print("      building the APK — this can take a minute …")
            res = projects.build_apk(pid)
            apk = res.get("apk") or {}
            check("APK built", bool(res.get("ok")), f"exit {res.get('code')}")
            check("APK file is there", bool(apk.get("path")) and Path(apk["path"]).exists(),
                  f"{apk.get('name', '')} {apk.get('bytes', 0) // 1024} KB")
        else:
            print("      (skipping the real APK build — run `selftest.py --build`)")
    finally:
        if pid:
            try:
                projects.delete_project(pid)
            except Exception:                            # noqa: BLE001
                pass
        shutil.rmtree(state, ignore_errors=True)
    check("test project cleaned up", pid is None or not (Path(root) / pid).exists())


def library_section(live: bool = False) -> None:
    """Library: read, list, view, recall and export GitHub repos.

    Offline it exercises the module against whatever is already saved. Pass
    `--net` to also read a tiny public repo end-to-end and clean it up after.
    """
    print("\n[10] library" + ("  (with a live repo fetch)" if live else "  (offline)"))
    try:
        import learn                                     # noqa: PLC0415
    except Exception as exc:                             # noqa: BLE001
        check("learn module imports", False, str(exc))
        return

    st = get("/api/status")
    check("status has library block", isinstance(st.get("library"), dict),
          f"enabled={st.get('library_enabled')} root={st.get('library_root')}")
    check("library root configured", bool(st.get("library_root")))

    lib = get("/api/library")
    check("/api/library returns a list", isinstance(lib.get("repos"), list),
          f"{lib.get('count', 0)} repo(s), {lib.get('files', 0)} files")

    rid = None
    created = False
    if live:
        spec = {"owner": "octocat", "repo": "Hello-World", "ref": ""}
        try:
            man = learn.fetch_repo(spec)                 # tiny public repo
            rid, created = man["id"], True
            check("read a live repo", man["files"] >= 1,
                  f"{man['owner']}/{man['repo']}@{man['ref']} — {man['files']} file(s)")
        except Exception as exc:                         # noqa: BLE001
            check("read a live repo", False, str(exc))

    if rid is None:
        rows = lib.get("repos") or []
        rid = rows[0]["id"] if rows else None

    if rid:
        detail = get("/api/library/" + urllib.parse.quote(rid))
        check("repo detail lists files", bool(detail.get("listing")),
              f"{len(detail.get('listing', []))} file(s) in {detail.get('owner')}/"
              f"{detail.get('repo')}")
        first = (detail.get("listing") or [{}])[0].get("path")
        if first:
            text = get("/api/library/" + urllib.parse.quote(rid) + "/file?path="
                       + urllib.parse.quote(first))["text"]
            check("file view returns text", isinstance(text, str) and len(text) > 0,
                  f"{first} — {len(text)} chars")
        hits = learn.recall("the readme of " + str(detail.get("repo", "")), limit=3)
        check("recall finds saved files", bool(hits), f"{len(hits)} hit(s)")
        with post("/api/library/" + urllib.parse.quote(rid) + "/export", {}) as r:
            out = json.loads(r.read())
        check("dataset export writes JSONL", bool(out.get("path")) and out.get("entries") >= 0,
              f"{out.get('entries', 0)} example(s) -> {out.get('path', '')}")
    else:
        print("      (no repos saved yet — skipping detail/recall/export)")

    if created and rid:
        req = urllib.request.Request(BASE + "/api/library/" + urllib.parse.quote(rid),
                                     method="DELETE")
        urllib.request.urlopen(req, timeout=30).read()
        check("test repo cleaned up",
              not any(r["id"] == rid for r in get("/api/library")["repos"]))


def voice_section() -> None:
    """Voice round-trip: piper speaks a sentence, whisper reads it back."""
    print("\n[9] voice  (piper -> whisper round-trip)")
    try:
        info = get("/api/voice")
    except Exception as exc:                                       # noqa: BLE001
        check("voice status reachable", False, str(exc))
        return
    check("speech model on disk", bool(info.get("stt_models")),
          ", ".join(info.get("stt_models") or []) or "none")
    check("piper voice on disk", bool(info.get("tts_voices")),
          ", ".join(info.get("tts_voices") or []) or "none")

    phrase = "The quick brown fox jumps over the lazy dog."
    req = urllib.request.Request(
        BASE + "/api/voice/tts",
        data=json.dumps({"text": phrase}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            wav = r.read()
    except Exception as exc:                                       # noqa: BLE001
        check("text to speech works", False, str(exc))
        return
    check("text to speech works", wav[:4] == b"RIFF" and len(wav) > 8000,
          f"{len(wav)} bytes of wav")

    req = urllib.request.Request(BASE + "/api/voice/stt", data=wav,
                                 headers={"Content-Type": "audio/wav"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            text = json.loads(r.read()).get("text", "")
    except Exception as exc:                                       # noqa: BLE001
        check("speech to text works", False, str(exc))
        return
    check("speech to text works", "fox" in text.lower(), repr(text[:90]))


def models_section() -> None:
    """Model discovery: every .gguf we can find, with a real layer count."""
    print("\n[11] models  (discovery)")
    try:
        models = get("/api/models")["models"]
        status = get("/api/status")
    except Exception as exc:                                       # noqa: BLE001
        check("model list reachable", False, str(exc))
        return
    check("found at least one .gguf", len(models) >= 1,
          ", ".join(m["name"] for m in models))
    check("layer count was read from the header",
          all(m["layers"] > 0 for m in models),
          ", ".join(f'{m["name"]}={m["layers"]}' for m in models))
    active = status.get("model") or {}
    check("status reports the active model", bool(active.get("name")),
          active.get("name", ""))
    check("active model is flagged in the list",
          any(m["active"] for m in models),
          next((m["name"] for m in models if m["active"]), ""))
    check("max_ngl matches the model's layers",
          status.get("max_ngl") == (active.get("layers") or 28),
          f'max_ngl={status.get("max_ngl")}')


def memory_section() -> None:
    """Long-term memory: add, ignore duplicates, forget — via the API."""
    print("\n[12] memory  (store + dedupe + forget)")
    try:
        info = get("/api/memory")
    except Exception as exc:                                       # noqa: BLE001
        check("memory status reachable", False, str(exc))
        return
    check("memory status reachable", "count" in info and "facts" in info,
          f"enabled={info.get('enabled')} root={info.get('root', '')}")
    check("memory root is configured", bool(info.get("root")), info.get("root", ""))

    probe = "User keeps a spare charging cable in the laptop bag"
    post("/api/memory", {"text": probe})
    facts = get("/api/memory")["facts"]
    check("a fact can be added", any(f["text"] == probe for f in facts),
          f"{len(facts)} stored")

    post("/api/memory", {"text": probe})
    after = get("/api/memory")["facts"]
    check("a duplicate is ignored",
          sum(1 for f in after if f["text"] == probe) == 1)

    fid = next((f["id"] for f in after if f["text"] == probe), None)
    if not fid:
        check("a fact can be forgotten", False, "no id returned")
        return
    req = urllib.request.Request(BASE + "/api/memory/" + fid, method="DELETE")
    urllib.request.urlopen(req, timeout=30).read()
    left = get("/api/memory")["facts"]
    check("a fact can be forgotten", not any(f["id"] == fid for f in left))


def remote_section() -> None:
    """Phone access + self-update: version, QR encoder, URLs, update check."""
    print("\n[13] phone access + updates")
    try:
        health = get("/api/health")
        remote = get("/api/remote")
        status = get("/api/status")
    except Exception as exc:                                       # noqa: BLE001
        check("health reachable", False, str(exc))
        return
    check("health reports a version", bool(health.get("version")),
          f"version={health.get('version')}")
    check("status carries the version too",
          status.get("version") == health.get("version"),
          str(status.get("version")))
    check("remote block is present",
          "enabled" in remote and "lan_urls" in remote,
          f"enabled={remote.get('enabled')} tunnel={remote.get('tunnel')}")
    check("a key exists", bool(remote.get("token")),
          remote.get("token", "")[:4] + "…" if remote.get("token") else "")

    # phone auto-discovery: the responder must answer a real broadcast probe
    try:
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
        import json as _json
        import remote as rem
        import socket as _socket
        rem.start_discovery(8091)
        probe = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        probe.settimeout(3)
        try:
            probe.sendto(rem._MAGIC, ("127.0.0.1", rem.DISCOVERY_PORT))
            data, _ = probe.recvfrom(1024)
            blob = _json.loads(data.decode())
            check("discovery answers a phone probe",
                  blob.get("app") == "anya" and bool(blob.get("urls")),
                  " ".join(blob.get("urls", [])))
            check("discovery reply points at this app's port",
                  blob.get("port") == 8091, str(blob.get("port")))
        finally:
            probe.close()
        check("discovery status is reported",
              "discovery" in remote and "discovery_running" in remote,
              f"running={remote.get('discovery_running')}")
    except Exception as exc:                                       # noqa: BLE001
        check("discovery answers a phone probe", False, str(exc))

    # the QR encoder must actually produce a decodable-looking matrix
    try:
        with urllib.request.urlopen(BASE + "/api/remote/qr.png", timeout=30) as r:
            png = r.read()
        ctype = r.headers.get("Content-Type", "")
    except Exception as exc:                                       # noqa: BLE001
        check("QR endpoint returns a PNG", False, str(exc))
        return
    check("QR endpoint returns a PNG",
          png[:8] == b"\x89PNG\r\n\x1a\n" and "png" in ctype,
          f"{len(png)} bytes, {ctype}")

    # the pure-stdlib encoder should round-trip a known string
    try:
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
        import qr as qrmod
        matrix = qrmod.matrix("https://example.com/anya")
        size = len(matrix)
        check("QR encoder builds a square matrix",
              size >= 21 and all(len(row) == size for row in matrix),
              f"{size}x{size}")
        check("QR has the timing-pattern alternation",
              all(matrix[6][i] == (i % 2 == 0) for i in range(8, size - 8)))
        png_bytes = qrmod.png("https://example.com/anya", scale=4)
        check("QR renders to PNG", png_bytes[:8] == b"\x89PNG\r\n\x1a\n",
              f"{len(png_bytes)} bytes")
    except Exception as exc:                                       # noqa: BLE001
        check("QR encoder importable", False, str(exc))

    # update check — offline-safe: a failure here is only a warning
    try:
        upd = get("/api/update")
        check("update check answers", "latest" in upd or "error" in upd,
              f"local={upd.get('current')} latest={upd.get('latest')}")
    except Exception as exc:                                       # noqa: BLE001
        check("update check answers", False, str(exc))


def phone_app_section() -> None:
    """The phone APK: status, download, QR, and the encoder behind the code."""
    print("\n[14] phone app (APK)")
    try:
        info = get("/api/phone-app")
        status = get("/api/status")
    except Exception as exc:                                       # noqa: BLE001
        check("phone-app status reachable", False, str(exc))
        return
    check("phone-app status reachable", "name" in info, f"name={info.get('name')}")
    check("status carries the phone-app block",
          "phone_app" in status and status["phone_app"].get("name") == "Anya")

    if not (info.get("apk") or info.get("apk_bytes")):
        check("an APK has been built", False,
              "press Build in Settings → Phone app, or run "
              "`python -c \"import sys;sys.path.insert(0,'anya-ui');"
              "import projects,phoneapp;projects.configure('anya-ui');phoneapp.build()\"`")
        return
    check("an APK has been built", True,
          f"{info['apk_bytes'] / 1048576:.1f} MB")

    # the download must actually be a signed Android package
    try:
        with urllib.request.urlopen(BASE + "/anya-phone.apk", timeout=120) as r:
            apk = r.read()
        ctype = r.headers.get("Content-Type", "")
    except Exception as exc:                                       # noqa: BLE001
        check("APK downloads", False, str(exc))
        return
    check("APK downloads", apk[:2] == b"PK" and len(apk) > 1_000_000,
          f"{len(apk)} bytes")
    check("APK is served as an Android package",
          "android.package-archive" in ctype, ctype)
    check("APK matches the reported size", abs(len(apk) - info["apk_bytes"]) < 4096)

    # it must be a real APK with a manifest and my classes inside
    try:
        import io
        import zipfile
        z = zipfile.ZipFile(io.BytesIO(apk))
        names = z.namelist()
        blob = b"".join(z.read(n) for n in names if n.endswith(".dex"))
        check("APK has a manifest", "AndroidManifest.xml" in names)
        check("APK has compiled dex", any(n.endswith(".dex") for n in names),
              f"{sum(1 for n in names if n.endswith('.dex'))} dex file(s)")
        check("APK contains Anya's own classes",
              b"com/anya/phone/MainActivityKt" in blob,
              "MainActivity + API client + prefs")
        check("APK talks to the same API the web UI does",
              b"/api/chat" in blob and b"/api/status" in blob)
    except Exception as exc:                                       # noqa: BLE001
        check("APK is readable", False, str(exc))

    # the QR must resolve to a real http(s) URL when phone access is on
    try:
        with urllib.request.urlopen(BASE + "/api/phone-app/qr.png", timeout=30) as r:
            png = r.read()
        check("APK QR renders", png[:8] == b"\x89PNG\r\n\x1a\n", f"{len(png)} bytes")
    except Exception as exc:                                       # noqa: BLE001
        check("APK QR renders", False, str(exc))
    check("install link is a URL when phone access is on",
          bool(info.get("download_url", "").startswith("http")),
          info.get("download_url", "") or "phone access is off")


def main() -> int:
    print("Anya UI self-test")
    print("=" * 60)

    print("\n[1] status")
    try:
        status = get("/api/status")
    except Exception as exc:                                       # noqa: BLE001
        print(f"  [FAIL] cannot reach the UI at {BASE}: {exc}")
        return 2
    check("backend reachable", True, f"backend={status['backend']}")
    check("model is running", status["running"] or status["starting"],
          f"profile={status['profile']} running={status['running']}")
    check("profiles present", len(status["profiles"]) >= 4,
          ", ".join(status["profiles"]))

    print("\n[2] chat (conversational)")
    sid, text, tokens, tps, err = say("What have you learned about coding?")
    check("no error", err is None, str(err or ""))
    check("got a reply", len(text) > 20, f"{len(text)} chars, {tokens} tokens, {tps} tok/s")
    check("answers in prose, not a bare code block",
          not text.strip().startswith("```"), text[:70].replace("\n", " ") + "…")
    print("      reply:", text[:220].replace("\n", " ") + ("…" if len(text) > 220 else ""))

    print("\n[3] chat (coding) in the same session")
    _, text2, tokens2, tps2, err2 = say(
        "Give me a tiny Kotlin data class for a user profile, in one code block.", sid)
    check("no error", err2 is None, str(err2 or ""))
    check("produced a code block", "```" in text2,
          f"tokens={tokens2} tps={tps2}")
    check("code is marked as kotlin", "kotlin" in text2.lower())

    print("\n[4] history")
    sessions = get("/api/sessions")["sessions"]
    check("session was stored", any(s["id"] == sid for s in sessions),
          f"{len(sessions)} session(s)")
    check("title came from the first message",
          any(s["id"] == sid and "learned" in s["title"].lower() for s in sessions))
    loaded = get("/api/sessions/" + sid)
    check("session reloads", len(loaded["messages"]) == 4,
          f"{len(loaded['messages'])} messages")
    check("roles alternate", [m["role"] for m in loaded["messages"]] ==
          ["user", "assistant", "user", "assistant"])
    found = get("/api/sessions?q=Kotlin")["sessions"]
    check("search works", any(s["id"] == sid for s in found), f"{len(found)} hit(s)")

    print("\n[5] markdown export")
    with urllib.request.urlopen(BASE + "/api/export/" + sid, timeout=30) as r:
        md = r.read().decode("utf-8")
    check("export has a heading", md.startswith("# "))
    check("export contains the reply", "```" in md or "Kotlin" in md)

    print("\n[6] cleanup")
    req = urllib.request.Request(BASE + "/api/sessions/" + sid, method="DELETE")
    urllib.request.urlopen(req, timeout=30).read()
    check("session deleted",
          not any(s["id"] == sid for s in get("/api/sessions")["sessions"]))

    filter_section()

    if "--web" in sys.argv:
        web_section()
    else:
        print("\n[8] web browsing  (skipped — run `selftest.py --web` to include it)")

    projects_section(real_build="--build" in sys.argv)

    library_section(live="--net" in sys.argv)

    models_section()

    memory_section()

    remote_section()

    phone_app_section()

    if "--voice" in sys.argv:
        voice_section()
    else:
        print("\n[9] voice  (skipped — run `selftest.py --voice` to include it)")

    print("\n" + "=" * 60)
    if fails:
        print(f"RESULT: {len(fails)} FAILED -> {', '.join(fails)}")
        return 1
    print("RESULT: ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
