#!/usr/bin/env python
"""
anya_ui.py — Anya's own chat interface.

A small, dependency-free (standard library only) web app that gives Anya a
proper front-end instead of the bare llama.cpp page:

  * clean dark chat UI served on http://127.0.0.1:8091
  * every conversation saved to SQLite, with a sidebar to browse/search the past
  * a Power panel that trades speed for memory so you can game while she runs:
      turbo / balanced / lite / cpu / off  plus a fine-grained layer slider
  * talks to Anya through llama-server (which it starts and supervises) or
    through Ollama, whichever you prefer

Run it:
    S:\\envs\\ai\\Scripts\\python.exe anya-ui\\anya_ui.py

Then open http://127.0.0.1:8091  (the desktop icon does both for you).
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ---------------------------------------------------------------------------
# paths & defaults
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent          # ...\anya-ui
PROJECT = ROOT.parent                           # project root
CONFIG_PATH = ROOT / "config.json"
DB_PATH = ROOT / "anya_chats.db"
INDEX_HTML = ROOT / "index.html"
LOG_DIR = Path(r"S:\tools\logs")

if str(ROOT) not in sys.path:              # so "import web" finds anya-ui\web.py
    sys.path.insert(0, str(ROOT))
import web                                                       # noqa: E402
import projects                                                  # noqa: E402
import learn                                                     # noqa: E402
import site_tools                                                # noqa: E402
import voice                                                     # noqa: E402
import memory                                                    # noqa: E402
import remote                                                    # noqa: E402
import updater                                                   # noqa: E402
import qr                                                        # noqa: E402
import phoneapp                                                  # noqa: E402

ANYA_VERSION = "0.17.0"


def anya_version() -> str:
    """The version Anya reports — from VERSION if present, else the constant."""
    try:
        v = (PROJECT / "VERSION").read_text(encoding="utf-8").strip()
        return v or ANYA_VERSION
    except Exception:                                             # noqa: BLE001
        return ANYA_VERSION

SYSTEM_PROMPT = (
    "You are Anya, a friendly assistant that runs entirely on the user's own PC. "
    "Your name is Anya.\n\n"
    "You are a normal chatbot AND a coding helper:\n"
    "- If the user is just chatting, answer in natural, warm, conversational prose. "
    "Do not dump code.\n"
    "- If the user asks for code, or code is clearly the right answer, write it in a "
    "fenced code block with the language tag, with a short explanation around it.\n"
    "- Keep replies concise and readable. Match the user's tone.\n"
    "- Answer as Anya, in your own voice. Never write the user's lines for them, "
    "never invent a question-and-answer dialogue, and never role-play both sides of "
    "the conversation.\n"
    "- Only output raw code with no explanation when the user explicitly asks for "
    "code only.\n\n"
    "You're a strong general coding helper, especially with Python and Kotlin for "
    "Android (including Jetpack Compose).\n\n"
    "If you're asked what you've learned, what you know, or about yourself, answer "
    "honestly and briefly: you're a small open coding model running on the user's own "
    "PC, fine-tuned for coding help, with a local library of GitHub files you've read "
    "and a memory of facts the user has told you. Do NOT invent a personal history, "
    "past jobs, training anecdotes, or specific file formats you were 'trained on'.\n\n"
    "You run fully offline: you have no internet access and you never claim to. If "
    "you don't know something, say so instead of inventing it.\n\n"
    "Read the user's words carefully and answer the actual question they asked. "
    "Do not guess at a topic from a single word, and never drift into unrelated "
    "subjects. In particular you have NOTHING to do with real estate, housing, "
    "rentals, listings, mortgages, or property searches (no Zillow-style content) — "
    "if a message mentions homes, houses, apartments, listings, or property, treat it "
    "as off-topic for you and briefly say you can't help with that, then steer back to "
    "coding, Android, or general chat. Never invent tool names or fake data."
)

# Appended to the system prompt only while the Web toggle is on. Anya was trained
# to say she is offline, so this has to explicitly overrule that — otherwise she
# refuses to use the results she is handed.
WEB_PROMPT = (
    "\n\nWeb browsing is switched ON in this app right now, and this overrides "
    "everything above about being offline: you *can* look things up, and you may "
    "say so if asked.\n\n"
    "You cannot browse by yourself. Instead, when you need current facts or the "
    "contents of a page, reply with ONLY one small JSON object on its own, and "
    "nothing else:\n\n"
    '{"name": "web_search", "arguments": {"query": "the words to search for"}}\n\n'
    "or, to read one specific page:\n\n"
    '{"name": "web_open", "arguments": {"url": "https://example.com/page"}}\n\n'
    "The app runs it and sends you back the results, and then you answer in your "
    "normal voice, in your own words. Those results are the only web you have.\n\n"
    "Rules:\n"
    "- If you are already given web results or a page below, use them and do NOT "
    "search again — answer from what you have been handed.\n"
    "- Otherwise search whenever the answer needs current, checkable or specific "
    "facts — versions, releases, prices, news, dates, \"latest\", \"today\", or "
    "anything you only half-remember. Ordinary conversation and code you already "
    "know need no search.\n"
    "- A reply is either one tool call on its own, or a normal answer — never a "
    "tool call in the middle of prose.\n"
    "- Never write a link, a version number or a fact that wasn't in what you were "
    "given. If you were given nothing, answer from what you know but do NOT invent "
    "sources or pretend you looked something up.\n"
    "- Pages may be cut short; mention it if that matters.\n"
    "- If you used web results, finish with a short 'Sources' list of the links "
    "you used, as markdown links."
)

# Appended only while the Library is on. Teaching repos the user has asked Anya to
# read live on disk; she reaches them with the same one-JSON-object protocol.
LIBRARY_PROMPT = (
    "\n\nA local code library is switched ON. The user has saved whole GitHub "
    "repositories for you, and the app has read every text file in them. If the "
    "question is about code in one of those repos, ask to see the relevant files by "
    "replying with ONLY one small JSON object:\n\n"
    '{"name": "recall", "arguments": {"query": "what to look for"}}\n\n'
    "The app returns the matching file excerpts, and then you answer from them in "
    "your normal voice. To read a repository the user names, reply:\n\n"
    '{"name": "learn_repo", "arguments": {"repo": "owner/name"}}\n\n'
    "Rules:\n"
    "- Use recall ONLY when the answer genuinely depends on the actual contents of "
    "a repo the user saved or named (a specific class, function, build file, or "
    "config in those repos). Do not guess at file contents.\n"
    "- Do NOT recall when the user asks you to write, explain, or show new code from "
    "scratch (e.g. 'write me a data class', 'hello world', 'how do I ...'). Just "
    "answer directly with the code — you already know how to do that.\n"
    "- Never claim a file says something it does not. If recall returns nothing "
    "useful, say plainly that it isn't in the library.\n"
    "- Reading a repo sends it to the local library only; it does not train you.\n"
    "- Ordinary conversation and code you already know need no tool call."
)


# Appended only while Projects is on. Anya cannot touch the disk herself, so this
# teaches her the same "reply with one small JSON object" protocol the web uses.
PROJECTS_PROMPT = (
    "\n\nProjects are switched ON: you can create a project on this PC, write real "
    "files into it, keep a task list, and build a real Android APK that can be "
    "installed on a phone.\n\n"
    "You cannot touch the disk yourself. To change something, reply with ONLY one "
    "small JSON object on its own and nothing else; the app performs it and sends "
    "you the result. These are the ones you may use:\n\n"
    "Start a project (an Android one already comes with a working scaffold):\n"
    '{"name": "new_project", "arguments": {"name": "Hello World"}}\n\n'
    "Write or replace a file (leave out \"project\" for the current one; put the whole "
    "file in \"content\", using \\n for new lines):\n"
    '{"name": "write_file", "arguments": {"path": "app/src/main/java/com/anya/'
    'hello/MainActivity.kt", "content": "package com.anya.hello\\n\\n..."}}\n\n'
    "Add a task, or move one along (status is todo, doing or done):\n"
    '{"name": "project_task", "arguments": {"title": "Add the button", "status": "doing"}}\n\n'
    "Build the APK:\n"
    '{"name": "build_apk", "arguments": {}}\n\n'
    "See or read what is there:\n"
    '{"name": "list_files", "arguments": {}}\n'
    '{"name": "read_file", "arguments": {"path": "app/build.gradle.kts"}}\n\n'
    "Run one allowed command inside the project (gradlew, javac, java, adb, git, "
    "python):\n"
    '{"name": "run_command", "arguments": {"command": "gradlew assembleDebug"}}\n\n'
    "Rules:\n"
    "- Work in small steps: one tool call per reply, then read the result and carry "
    "on. Say in a sentence what you are doing, then give the JSON object.\n"
    "- Never call the same tool twice with the same arguments. One look at the files "
    "is enough — then write a file, or build.\n"
    "- Never invent a result. If a build fails, read the error, fix the file, and "
    "try again — or tell the user plainly what is wrong.\n"
    "- An Android project already builds as it is, so a normal change is: write one "
    "file, then build_apk.\n"
    "- Write Kotlin, and edit the file that is already there (usually "
    "app/src/main/java/.../MainActivity.kt). Do not invent layouts or resources: "
    "R.layout.* and new XML files will not exist, and the build will fail.\n"
    "- If a build fails, read the error, change the file it names, then call "
    "build_apk again. Never call gradlew by hand — build_apk does that.\n"
    "- Files you write must stay inside the project. A path outside it is sent to "
    "the user to approve.\n"
    "- If the user is only chatting or asking for code to read, just answer normally "
    "— do not create a project or write files."
)

# Appended only for unattended runs: she takes one step, gets the result, repeats.
AUTOPILOT_PROMPT = (
    "\n\nYou are now working UNATTENDED (autopilot) on the user's project. Take "
    "exactly ONE small step per turn and reply with ONLY one JSON object and "
    "nothing else — no prose, no code fences. You will be given the result and "
    "then asked for the next step.\n"
    "When the goal is met, reply with {\"name\": \"finish\"} and nothing else.\n"
    "Rules: never repeat a step you have already done. Work in small steps. If a "
    "build fails, read the error, change the file it names, then call build_apk. "
    "Prefer editing MainActivity.kt over inventing new layouts or resources."
)

DEFAULTS: dict = {
    "backend": "llama",              # "llama" (llama-server) or "ollama"
    "host": "127.0.0.1",
    "port": 8091,
    "profile": "balanced",
    "custom": {"ngl": 24, "ctx": 4096, "threads": 0},
    "idle_unload_min": 0,            # 0 = never; otherwise minutes of silence
    "system_prompt": SYSTEM_PROMPT,
    "temperature": 0.6,
    "llama_server": r"S:\tools\llama-vulkan\llama-server.exe",
    "gguf": str(PROJECT / "models" / "anya-f16.gguf"),
    "models_dir": r"S:\models",      # extra folder to look for .gguf models in
    "llama_port": 8090,
    "ollama_url": "http://127.0.0.1:11434",
    "ollama_model": "anya",
    "web_enabled": False,            # let her search the web and read pages
    "web_max_pages": 3,              # tool rounds allowed per reply
    "web_chars": 1400,               # characters kept from each page fetched
    "projects_enabled": True,        # let her create projects, write files and build APKs
    "projects_root": r"S:\anya-projects",   # the only place she may write files
    "library_enabled": True,         # let her read GitHub repos and recall them in chat
    "library_root": r"S:\anya-library",     # where saved repos (plain files) live
    "library_recall": True,          # quietly pull relevant saved files into answers
    "github_token": "",              # personal access token, only for private repos
    "site_enabled": True,             # edit and publish GitHub Pages from the UI
    "site_repo": "SeanTheGoon67/SeanTheGoon67.github.io",
    "site_branch": "main",
    "site_dir": str(PROJECT / "site"),
    "site_use_html": True,           # generate index.html from index.md on save/build
    "ui_theme": "midnight",          # UI colour theme, picked on the Themes tab
    "ui_accent": "",                 # custom accent (#rrggbb); "" = use the theme's own
    "voice_stt": True,               # show the mic button (push-to-talk -> whisper)
    "voice_tts": False,              # auto-speak replies (piper); mic/speaker toggle
    "voice_stt_model": "small.en",   # whisper checkpoint in S:\voices\whisper
    "voice_piper_voice": "en_US-lessac-medium",  # piper voice in S:\voices\piper
    "voice_device": "cpu",           # STT device: cpu (default, shares the GPU badly
                                     # with the LLM) or cuda (fast, needs free VRAM)
    "memory_enabled": True,          # remember durable facts about the user
    "memory_learn": True,            # learn new facts automatically after replies
    "memory_dir": r"S:\anya-memory",  # where the facts file lives
    "memory_inject": 30,             # how many facts to feed her per message
    "gh_path": "",                   # optional: path to a gh binary, if you have one
    "remote_enabled": False,         # let a phone reach this UI (binds all interfaces)
    "remote_token": "",              # shared key for the phone; generated on first use
    "remote_tunnel": "off",          # "off" | "cloudflare" (quick tunnel, no account)
    "remote_tunnel_on_start": False, # raise the tunnel automatically with the UI
    "remote_discovery": True,        # answer a phone's UDP probe so it finds this PC
    "measured": {},                  # filled in at runtime: profile -> {vram_mb, tps}
}

# GPU layers (of 28) + context + cpu threads. "off" stops the model completely.
PROFILES: dict = {
    "turbo":    {"label": "Turbo",    "ngl": 28, "ctx": 8192, "threads": 0, "stop": False},
    "balanced": {"label": "Balanced", "ngl": 24, "ctx": 4096, "threads": 0, "stop": False},
    "lite":     {"label": "Lite",     "ngl": 8,  "ctx": 4096, "threads": 4, "stop": False},
    "cpu":      {"label": "CPU only", "ngl": 0,  "ctx": 2048, "threads": 6, "stop": False},
    "off":      {"label": "Off",      "ngl": 0,  "ctx": 0,    "threads": 0, "stop": True},
}

# Real measurements from this PC (F16 1.5B, RTX 5050) used to calibrate estimates:
#   ngl=0  -> 80 MiB VRAM / 3072 MiB RAM     ngl=8  -> 1178 / 2419
#   ngl=28 -> 3043 MiB VRAM / 554 MiB RAM    (all at 4096 ctx; KV cache = 112 MiB)
VRAM_ANCHORS = [(0, 80), (8, 1178), (28, 3043)]
RAM_ANCHORS = [(0, 3072), (8, 2419), (28, 554)]
KV_PER_4096 = 112.0          # MiB of KV cache at 4096 context, all layers

# tokens/sec is only shown once it has actually been measured for a profile
# (speed on this PC swings hugely depending on whether a game is running).
ESTIMATES: dict = {}


def _interp(anchors: list, n: float) -> float:
    n = max(0.0, min(float(n), 28.0))
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x0 <= n <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (n - x0) / (x1 - x0)
    return anchors[-1][1]


def estimate_footprint(ngl: int, ctx: int) -> dict:
    """How much VRAM/RAM a given number of GPU layers and context should cost."""
    ngl = max(0, min(int(ngl), 28))
    ctx = max(0, int(ctx))
    kv = KV_PER_4096 * (ctx / 4096.0)
    gpu_fixed = _interp(VRAM_ANCHORS, ngl) - KV_PER_4096 * (ngl / 28.0)
    ram_fixed = _interp(RAM_ANCHORS, ngl) - KV_PER_4096 * (1 - ngl / 28.0)
    vram = 80 if ngl == 0 else max(80.0, gpu_fixed + kv * (ngl / 28.0))
    ram = ram_fixed + kv * (1 - ngl / 28.0)
    return {"vram_mb": int(round(vram)), "ram_mb": int(round(ram))}


# ---------------------------------------------------------------------------
# model files (.gguf) — discovery, a tiny metadata reader, profile retuning
# ---------------------------------------------------------------------------

def model_dirs() -> list:
    """Folders searched for .gguf models, active one first."""
    dirs = []
    active = Path(str(cfg().get("gguf") or ""))
    if active.parent.is_dir():
        dirs.append(active.parent)
    for d in (cfg().get("models_dir"), str(PROJECT / "models")):
        if d:
            p = Path(d)
            if p.is_dir() and p not in dirs:
                dirs.append(p)
    return dirs


def _gguf_read_header(path: Path, max_keys: int = 400) -> dict:
    """Pull a few facts out of a .gguf header without deps.

    GGUF is: magic, version(u32), tensor_count(u64), kv_count(u64), then
    key/value pairs. We only need the architecture and block_count, so we stop
    as soon as we have those — but we still walk every value type correctly so
    the stream never desyncs. Never raises: an unreadable model just reports {}.
    """
    import struct
    info: dict = {}
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"GGUF":
                return info
            struct.unpack("<I", f.read(4))[0]        # version
            struct.unpack("<Q", f.read(8))[0]        # tensor_count
            kv_count = struct.unpack("<Q", f.read(8))[0]

            def r_str() -> str:
                n = struct.unpack("<Q", f.read(8))[0]
                return f.read(n).decode("utf-8", "replace")

            def r_val(t: int):
                if t == 0:
                    return struct.unpack("<B", f.read(1))[0]
                if t == 1:
                    return struct.unpack("<b", f.read(1))[0]
                if t == 2:
                    return struct.unpack("<H", f.read(2))[0]
                if t == 3:
                    return struct.unpack("<h", f.read(2))[0]
                if t == 4:
                    return struct.unpack("<I", f.read(4))[0]
                if t == 5:
                    return struct.unpack("<i", f.read(4))[0]
                if t == 6:
                    return struct.unpack("<f", f.read(4))[0]
                if t == 7:
                    return bool(struct.unpack("<B", f.read(1))[0])
                if t == 8:
                    return r_str()
                if t == 10:
                    return struct.unpack("<Q", f.read(8))[0]
                if t == 11:
                    return struct.unpack("<q", f.read(8))[0]
                if t == 12:
                    return struct.unpack("<d", f.read(8))[0]
                if t == 9:                            # array: elem_type + count
                    et = struct.unpack("<I", f.read(4))[0]
                    cnt = struct.unpack("<Q", f.read(8))[0]
                    keep = min(cnt, 16)               # don't memorise a whole vocab
                    vals = [r_val(et) for _ in range(cnt)] if cnt <= 4096 else None
                    if vals is None:                  # huge array: read+discard
                        for _ in range(cnt):
                            r_val(et)
                        return f"[{cnt} items]"
                    return vals if cnt <= keep else vals[:keep] + ["…"]
                raise ValueError(f"unknown gguf type {t}")

            for _ in range(min(kv_count, max_keys)):
                key = r_str()
                t = struct.unpack("<I", f.read(4))[0]
                val = r_val(t)
                info[key] = val
                if key.endswith(".block_count"):
                    break
    except Exception:                                             # noqa: BLE001
        pass
    return info


def model_info(path) -> dict:
    """Size, layer count and native context for one .gguf (best-effort)."""
    p = Path(path)
    try:
        size_mb = int(round(p.stat().st_size / (1024 * 1024)))
    except OSError:
        size_mb = 0
    meta = _gguf_read_header(p)
    arch = str(meta.get("general.architecture") or "")
    layers = meta.get(f"{arch}.block_count") if arch else None
    native_ctx = meta.get(f"{arch}.context_length") if arch else None
    embd = meta.get(f"{arch}.embedding_length") if arch else None
    kinds = {"qwen2": "Qwen2", "qwen3": "Qwen3", "llama": "Llama", "gemma2": "Gemma 2",
             "gemma3": "Gemma 3", "phi3": "Phi-3", "qwen2moe": "Qwen2-MoE",
             "deepseek2": "DeepSeek", "mistral": "Mistral", "smollm2": "SmolLM2"}
    return {
        "name": p.name,
        "path": str(p),
        "size_mb": size_mb,
        "arch": arch,
        "family": kinds.get(arch, arch or "?"),
        "layers": int(layers) if isinstance(layers, int) else 0,
        "embedding": int(embd) if isinstance(embd, int) else 0,
        "native_ctx": int(native_ctx) if isinstance(native_ctx, int) else 0,
        "active": p.resolve() == Path(str(cfg().get("gguf") or "")).resolve()
        if str(cfg().get("gguf") or "") else False,
    }


def list_models() -> list:
    """Every .gguf we can find, de-duplicated, active first."""
    seen, out = set(), []
    for d in model_dirs():
        for p in sorted(d.glob("*.gguf")):
            key = str(p.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(model_info(p))
    out.sort(key=lambda m: (not m["active"], m["name"].lower()))
    return out


# Base fractions of the model's layers each preset offloads. The 1.5B has 28
# layers, so these reproduce the old 28/24/8/0 numbers exactly, while a bigger
# model with more layers scales up automatically.
PROFILE_FRACTIONS = {"turbo": 1.0, "balanced": 24 / 28, "lite": 8 / 28, "cpu": 0.0}


def active_layers() -> int:
    """Layer count of the model currently selected (defaults to 28)."""
    try:
        info = model_info(cfg().get("gguf"))
    except Exception:                                             # noqa: BLE001
        return 28
    return int(info.get("layers") or 0) or 28


def retune_profiles(layers: int) -> None:
    """Point each preset's GPU-layer count at this model's real layer count."""
    layers = max(1, int(layers))
    for name, frac in PROFILE_FRACTIONS.items():
        if name in PROFILES:
            PROFILES[name]["ngl"] = int(round(frac * layers))
            PROFILES[name]["layers"] = layers


def estimate_for_model(ngl: int, ctx: int) -> dict:
    """VRAM/RAM estimate that knows the real model size, not just the 1.5B."""
    try:
        info = model_info(cfg().get("gguf"))
    except Exception:                                             # noqa: BLE001
        info = {}
    layers = int(info.get("layers") or 0)
    size_mb = int(info.get("size_mb") or 0)
    if not layers or not size_mb:
        return estimate_footprint(ngl, ctx)
    ngl = max(0, min(int(ngl), layers))
    weights = size_mb * 0.92                       # leave room for the output layer
    per_layer = weights / layers
    kv = KV_PER_4096 * (ctx / 4096.0) * (size_mb / 1000.0) ** 0.5   # kv grows with width
    gpu = 80 + per_layer * ngl + kv * (ngl / layers)
    ram = per_layer * (layers - ngl) + kv * (1 - ngl / layers) + 500
    return {"vram_mb": int(round(gpu)), "ram_mb": int(round(ram))}

_cfg_lock = threading.RLock()
_config: dict = {}


def load_config() -> dict:
    global _config
    cfg = json.loads(json.dumps(DEFAULTS))
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception as exc:                                  # noqa: BLE001
            print(f"[!] config.json unreadable ({exc}); using defaults")
    _config = cfg
    return cfg


def save_config() -> None:
    with _cfg_lock:
        CONFIG_PATH.write_text(json.dumps(_config, indent=2), encoding="utf-8")


def cfg() -> dict:
    return _config


# ---------------------------------------------------------------------------
# phone / remote access + self-update helpers
# ---------------------------------------------------------------------------

def remote_token() -> str:
    """The shared key a phone must present. Generated on first use."""
    tok = str(cfg().get("remote_token") or "").strip()
    if not tok:
        import secrets
        tok = secrets.token_urlsafe(9)
        with _cfg_lock:
            _config["remote_token"] = tok
        save_config()
    return tok


def remote_urls() -> dict:
    """Base URLs someone could use to reach this UI from a phone."""
    port = int(cfg().get("port", 8091))
    ips = remote.lan_ips()
    lan = [f"http://{ip}:{port}" for ip in ips]
    ts = remote.tailscale_ip()
    return {
        "port": port,
        "lan": lan,
        "lan_url": lan[0] if lan else "",
        "tailscale_url": f"http://{ts}:{port}" if ts else "",
    }


def remote_status() -> dict:
    c = cfg()
    u = remote_urls()
    tun = remote.tunnel_status()
    best = tun.get("url") or u["tailscale_url"] or u["lan_url"]
    return {
        "enabled": bool(c.get("remote_enabled", False)),
        "host": c.get("host", "127.0.0.1"),
        "port": u["port"],
        "token": remote_token(),
        "lan_urls": u["lan"],
        "lan_url": u["lan_url"],
        "tailscale_url": u["tailscale_url"],
        "tunnel": c.get("remote_tunnel", "off"),
        "tunnel_on_start": bool(c.get("remote_tunnel_on_start", False)),
        "tunnel_running": bool(tun.get("running")),
        "tunnel_url": tun.get("url", ""),
        "tunnel_error": tun.get("error", ""),
        "cloudflared": bool(tun.get("installed")),
        "phone_url": best,
        "discovery": bool(c.get("remote_discovery", True)),
        "discovery_running": bool(remote.discovery_status().get("running")),
        "discovery_port": remote.discovery_status().get("port", 8092),
    }


def phone_status() -> dict:
    """Phone-app state for /api/status and the GUI's Phone app section."""
    try:
        st = phoneapp.status(remote_token())
    except Exception as exc:                                      # noqa: BLE001
        st = {"exists": False, "apk": "", "apk_bytes": 0, "error": str(exc)}
    st["download_url"] = phone_apk_url()
    st["apk_url"] = phone_apk_url()
    return st


def phone_apk_url() -> str:
    """An absolute URL a phone can use to fetch the APK, or '' if none.

    Prefers whatever route the phone is already using (tunnel, then Tailscale,
    then LAN), so the QR points somewhere that actually resolves for that phone.
    """
    if not phoneapp.published_apk():
        return ""
    u = remote_urls()
    tun = remote.tunnel_status()
    base = tun.get("url") or u["tailscale_url"] or u["lan_url"]
    if not base:
        return ""
    return base.rstrip("/") + "/anya-phone.apk"


def restart_soon(delay: float = 1.2) -> None:
    """Relaunch the UI in a fresh process (used after a settings/update change)."""
    def _go() -> None:
        time.sleep(delay)
        try:
            BACKEND.stop()
        except Exception:                                         # noqa: BLE001
            pass
        try:
            cmd = [sys.executable, str(ROOT / "anya_ui.py")] + sys.argv[1:]
            subprocess.Popen(cmd, cwd=str(PROJECT), close_fds=True,
                             creationflags=0x00000008 | 0x00000200)  # detached
        except Exception:                                         # noqa: BLE001
            pass
        time.sleep(0.4)
        os._exit(0)
    threading.Thread(target=_go, daemon=True).start()


# ---------------------------------------------------------------------------
# machine stats (no third-party libs)
# ---------------------------------------------------------------------------

class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def ram_used_gb() -> tuple[float, float]:
    st = _MEMORYSTATUSEX()
    st.dwLength = ctypes.sizeof(st)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
    total = st.ullTotalPhys / 1024 ** 3
    used = (st.ullTotalPhys - st.ullAvailPhys) / 1024 ** 3
    return round(used, 1), round(total, 1)


def _smiquery(fields: str) -> list[list[str]]:
    try:
        out = subprocess.run(
            ["nvidia-smi", f"--query-{fields}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8,
            creationflags=0x08000000,          # CREATE_NO_WINDOW
        )
        if out.returncode != 0:
            return []
        return [ln.split(",") for ln in out.stdout.strip().splitlines() if ln.strip()]
    except Exception:                                             # noqa: BLE001
        return []


def gpu_stats() -> dict:
    gpu = {"used_mb": 0, "total_mb": 0, "name": "unknown", "procs": {}}
    rows = _smiquery("gpu=name,memory.used,memory.total")
    if rows:
        name, used, total = rows[0]
        gpu.update(name=name.strip(), used_mb=int(used), total_mb=int(total))
    for row in _smiquery("compute-apps=pid,used_memory"):
        try:
            gpu["procs"][int(row[0])] = int(row[1])
        except (ValueError, IndexError):
            continue
    return gpu


def median_gpu_used(samples: int = 3) -> int:
    """GPU memory in use, median of a few quick samples (it fluctuates)."""
    vals = []
    for _ in range(samples):
        used = gpu_stats()["used_mb"]
        if used:
            vals.append(used)
        time.sleep(0.25)
    if not vals:
        return 0
    vals.sort()
    return vals[len(vals) // 2]


# ---------------------------------------------------------------------------
# chat history (SQLite)
# ---------------------------------------------------------------------------

_db_lock = threading.Lock()


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def db_init() -> None:
    with _db_lock, db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sessions("
            " id TEXT PRIMARY KEY, title TEXT, created REAL, updated REAL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS messages("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT,"
            " content TEXT, created REAL, tokens INTEGER DEFAULT 0,"
            " tps REAL DEFAULT 0, profile TEXT)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS ix_msg ON messages(session_id, id)")


def new_session(title: str = "New chat") -> str:
    sid = uuid.uuid4().hex[:12]
    now = time.time()
    with _db_lock, db() as conn:
        conn.execute("INSERT INTO sessions(id,title,created,updated) VALUES(?,?,?,?)",
                     (sid, title, now, now))
    return sid


def add_message(sid: str, role: str, content: str,
                tokens: int = 0, tps: float = 0.0, profile: str = "") -> int:
    now = time.time()
    with _db_lock, db() as conn:
        cur = conn.execute(
            "INSERT INTO messages(session_id,role,content,created,tokens,tps,profile)"
            " VALUES(?,?,?,?,?,?,?)", (sid, role, content, now, tokens, tps, profile))
        conn.execute("UPDATE sessions SET updated=? WHERE id=?", (now, sid))
        if role == "user":
            row = conn.execute("SELECT title FROM sessions WHERE id=?", (sid,)).fetchone()
            if row and row["title"] in ("New chat", "", None):
                conn.execute("UPDATE sessions SET title=? WHERE id=?",
                             (content.strip().replace("\n", " ")[:60] or "New chat", sid))
        return cur.lastrowid


def list_sessions(q: str = "") -> list[dict]:
    with db() as conn:
        if q:
            rows = conn.execute(
                "SELECT s.id, s.title, s.updated, COUNT(m.id) n FROM sessions s"
                " LEFT JOIN messages m ON m.session_id=s.id"
                " WHERE s.title LIKE ? OR s.id IN (SELECT session_id FROM messages"
                "   WHERE content LIKE ?) GROUP BY s.id ORDER BY s.updated DESC",
                (f"%{q}%", f"%{q}%")).fetchall()
        else:
            rows = conn.execute(
                "SELECT s.id, s.title, s.updated, COUNT(m.id) n FROM sessions s"
                " LEFT JOIN messages m ON m.session_id=s.id"
                " GROUP BY s.id ORDER BY s.updated DESC").fetchall()
    return [dict(r) for r in rows]


def get_session(sid: str) -> dict | None:
    with db() as conn:
        s = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        if not s:
            return None
        msgs = conn.execute(
            "SELECT role,content,created,tokens,tps,profile FROM messages"
            " WHERE session_id=? ORDER BY id", (sid,)).fetchall()
    return {"id": s["id"], "title": s["title"], "created": s["created"],
            "updated": s["updated"], "messages": [dict(m) for m in msgs]}


def delete_session(sid: str) -> None:
    with _db_lock, db() as conn:
        conn.execute("DELETE FROM messages WHERE session_id=?", (sid,))
        conn.execute("DELETE FROM sessions WHERE id=?", (sid,))


def clear_all_sessions() -> int:
    """Delete every saved conversation. Returns how many were removed."""
    with _db_lock, db() as conn:
        n = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM sessions")
    return int(n)


def rename_session(sid: str, title: str) -> None:
    with _db_lock, db() as conn:
        conn.execute("UPDATE sessions SET title=? WHERE id=?", (title[:80], sid))


def export_markdown(sid: str) -> str:
    s = get_session(sid)
    if not s:
        return "# Not found\n"
    out = [f"# {s['title']}", "",
           f"*Anya — exported {time.strftime('%Y-%m-%d %H:%M')}*", ""]
    for m in s["messages"]:
        who = "You" if m["role"] == "user" else "Anya"
        out += [f"### {who}", "", m["content"], ""]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# the model backend (llama-server, supervised)
# ---------------------------------------------------------------------------

class Backend:
    """Owns the llama-server process and knows how to talk to it."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.args: str | None = None          # args of the process we started
        self.lock = threading.RLock()
        self.gen_lock = threading.Lock()      # one generation at a time (see stream)
        self.starting = False
        self.start_error: str | None = None
        self.started_at: float | None = None
        self.last_activity = time.time()
        self.last_tps: float | None = None

    # -- urls ------------------------------------------------------------
    @property
    def port(self) -> int:
        return int(cfg().get("llama_port", 8090))

    @property
    def base(self) -> str:
        if cfg().get("backend") == "ollama":
            return str(cfg().get("ollama_url")).rstrip("/")
        return f"http://127.0.0.1:{self.port}"

    def _get(self, path: str, timeout: int = 5):
        req = urllib.request.Request(self.base + path)
        return urllib.request.urlopen(req, timeout=timeout)

    # -- process control --------------------------------------------------
    def healthy(self) -> bool:
        try:
            with self._get("/health", 3) as r:
                return r.status == 200
        except Exception:                                         # noqa: BLE001
            return False

    def serving_ours(self) -> bool:
        """True when whatever is on the port is serving *our* GGUF."""
        try:
            with self._get("/v1/models", 4) as r:
                data = json.loads(r.read())
            ids = [m.get("id", "") for m in data.get("data", [])]
            want = str(cfg()["gguf"]).replace("\\", "/").lower()
            return any(want in str(i).replace("\\", "/").lower() for i in ids)
        except Exception:                                         # noqa: BLE001
            return False

    def args_for(self, profile: str) -> str:
        p = PROFILES[profile]
        ctx = p["ctx"]
        threads = p["threads"]
        parts = [
            f'-m "{cfg()["gguf"]}"',
            f'--host 127.0.0.1 --port {self.port}',
            f'-c {ctx}',
            f'-ngl {p["ngl"]}',
        ]
        if threads:
            parts.append(f'--threads {threads}')
        return " ".join(parts)

    def start(self, profile: str) -> None:
        exe = cfg()["llama_server"]
        if not Path(exe).exists():
            raise RuntimeError(f"llama-server not found at {exe}")
        if not Path(cfg()["gguf"]).exists():
            raise RuntimeError(f"model not found at {cfg()['gguf']}")
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.args = self.args_for(profile)
        out = open(LOG_DIR / "llama-server.out.log", "w", encoding="utf-8")
        err = open(LOG_DIR / "llama-server.err.log", "w", encoding="utf-8")
        try:
            self.proc = subprocess.Popen(
                f'"{exe}" {self.args}', stdout=out, stderr=err,
                creationflags=0x08000000 | 0x00000200,   # NO_WINDOW | NEW_PROCESS_GROUP
                shell=False,
            )
        finally:
            # the child owns its own copies of these handles now
            out.close()
            err.close()
        self.started_at = time.time()

    def stop(self) -> None:
        with self.lock:
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.terminate()
                    self.proc.wait(timeout=8)
                except Exception:                                 # noqa: BLE001
                    try:
                        self.proc.kill()
                    except Exception:                             # noqa: BLE001
                        pass
            self.proc = None
            self.args = None
            self.started_at = None

    def wait_healthy(self, timeout: int = 180) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self.healthy():
                return True
            if self.proc and self.proc.poll() is not None:
                raise RuntimeError("llama-server exited during startup "
                                   "(see S:\\tools\\logs\\llama-server.err.log)")
            time.sleep(0.7)
        return False

    def wait_port_free(self, timeout: int = 20) -> None:
        """Make sure nothing else still holds our port before we bind it."""
        end = time.time() + timeout
        while time.time() < end:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=1.5)
                time.sleep(0.5)            # something still answers -> wait
            except Exception:                                         # noqa: BLE001
                return
        raise RuntimeError(f"port {self.port} is still in use by another program")

    def memory_from_log(self) -> dict:
        """Read llama.cpp's own memory breakdown — the honest footprint.

        Lines look like:
          | - Vulkan0 (RTX 5050) | 7910 = 7140 + (3043 = 2855 + 108 + 80) + ...
          | - Host               |                  554 =  534 +   4 + 16
        The GPU "self" value is exactly how much VRAM Anya holds, regardless of
        what else (a game, a browser) is using the card.
        """
        got: dict = {}
        try:
            text = (LOG_DIR / "llama-server.err.log").read_text(
                encoding="utf-8", errors="replace")
        except Exception:                                             # noqa: BLE001
            return got
        gpu = re.findall(r"\|\s*-\s*(?:Vulkan|CUDA)\d*[^|]*\|\s*\d+\s*=\s*\d+\s*\+\s*\(\s*(\d+)", text)
        host = re.findall(r"\|\s*-\s*Host\s*\|\s*(\d+)\s*=", text)
        if gpu:
            got["vram_mb"] = int(gpu[-1])
        if host:
            got["ram_mb"] = int(host[-1])
        return got

    def apply(self, profile: str, background: bool = True) -> dict:
        """Switch power profile. Restarts the server when the args change."""
        if profile not in PROFILES:
            raise RuntimeError(f"unknown profile {profile!r}")
        with _cfg_lock:
            _config["profile"] = profile
        save_config()

        if PROFILES[profile]["stop"]:
            self.stop()
            return {"ok": True, "applying": False, "profile": profile}

        want = self.args_for(profile)
        if self.proc and self.proc.poll() is None and self.args == want and self.healthy():
            self.record_measurement(profile)
            return {"ok": True, "applying": False, "profile": profile}

        if background:
            threading.Thread(target=self._restart, args=(profile,), daemon=True).start()
            return {"ok": True, "applying": True, "profile": profile}
        self._restart(profile)
        return {"ok": True, "applying": False, "profile": profile}

    def _restart(self, profile: str) -> None:
        self.starting = True
        self.start_error = None
        try:
            self.stop()
            # The old launcher / a previous run may still hold the port. Reclaim it.
            kill_stray_anya_servers()
            self.wait_port_free()
            self.start(profile)
            if not self.wait_healthy():
                raise RuntimeError("timed out waiting for the model to load")
            time.sleep(2.0)
            mem = self.memory_from_log()
            if mem:
                self.record_measurement(profile, mem, source="log")
            else:
                p = PROFILES[profile]
                self.record_measurement(
                    profile, estimate_for_model(p["ngl"], p["ctx"]), source="model")
        except Exception as exc:                                  # noqa: BLE001
            self.start_error = str(exc)
        finally:
            self.starting = False

    def record_measurement(self, profile: str, mem: dict | None = None,
                           source: str = "model") -> None:
        """Remember what this profile actually costs in VRAM and RAM."""
        mem = mem or {}
        with _cfg_lock:
            m = dict(_config.get("measured", {}))
        entry = dict(m.get(profile, {}))
        if PROFILES.get(profile, {}).get("stop"):
            entry["vram_mb"] = 0
            entry["ram_mb"] = 0
        else:
            if "vram_mb" in mem:
                entry["vram_mb"] = int(mem["vram_mb"])
            if "ram_mb" in mem:
                entry["ram_mb"] = int(mem["ram_mb"])
        entry["source"] = source
        m[profile] = entry
        with _cfg_lock:
            _config["measured"] = m
        save_config()

    def record_tps(self, profile: str, tps: float) -> None:
        """Attribute measured speed to the profile that produced it."""
        with _cfg_lock:
            m = dict(_config.get("measured", {}))
        entry = dict(m.get(profile, {}))
        entry["tps"] = round(tps, 1)
        m[profile] = entry
        with _cfg_lock:
            _config["measured"] = m
        save_config()

    def own_vram_mb(self) -> int | None:
        """Per-process VRAM when the driver exposes it, else the measured cost."""
        if self.proc:
            got = gpu_stats()["procs"].get(self.proc.pid)
            if got:
                return got
        prof = cfg().get("profile", "balanced")
        return cfg().get("measured", {}).get(prof, {}).get("vram_mb")

    # -- inference --------------------------------------------------------
    def _trim(self, messages: list[dict], ctx: int) -> list[dict]:
        """Keep the whole prompt inside the context window.

        Budgeted in characters (~3.4 per token) with room reserved for the reply.
        The system prompt always survives — if it alone is too big (a runaway
        recall block) it is truncated rather than dropped — and a single
        oversized message is trimmed instead of being let through, which is what
        used to trip llama-server's "request exceeds context size" error.
        """
        ctx = max(int(ctx or 4096), 512)
        reserve = min(1024, ctx // 4)
        # 2.4 chars/token is the pessimistic end we actually measured (recall
        # blocks full of code and JSON tokenise far denser than prose). Going
        # over budget is a hard 400 from llama-server, not a soft degradation.
        budget = max(2000, int((ctx - reserve) * 2.4))
        system = [m for m in messages if m["role"] == "system"]
        rest = [m for m in messages if m["role"] != "system"]

        used = 0
        kept_sys = []
        for m in system:
            content = m["content"]
            room = budget - used
            if len(content) > room:
                content = content[:max(room, 0)] + "\n…[context trimmed]"
            kept_sys.append({**m, "content": content})
            used += len(content)

        kept = []
        for m in reversed(rest):
            content = m["content"]
            size = len(content) + 16
            if used + size > budget:
                room = budget - used - 32
                if room < 300:
                    break
                content = content[:room] + "\n…[context trimmed]"
                size = len(content) + 16
                kept.append({**m, "content": content})
                used += size
                break
            used += size
            kept.append(m)
        return kept_sys + list(reversed(kept))

    def stream(self, messages: list[dict], on_token,
               temperature: float | None = None,
               nonblocking: bool = False) -> dict:
        """Stream a completion, one at a time.

        llama-server runs several slots, but overlapping requests (a reply and
        the quiet memory-extraction pass) can trip its context handling and come
        back as HTTP 400, so generations are serialised here. `nonblocking` lets
        the memory pass step politely aside when a real reply is in flight.
        """
        if nonblocking:
            if not self.gen_lock.acquire(blocking=False):
                raise RuntimeError("the model is busy")
        else:
            self.gen_lock.acquire()
        try:
            return self._stream_locked(messages, on_token, temperature)
        finally:
            self.gen_lock.release()

    def _stream_locked(self, messages: list[dict], on_token,
                       temperature: float | None = None) -> dict:
        """Stream a completion. Returns {tokens, tps, text}."""
        self.last_activity = time.time()
        prof = cfg().get("profile", "balanced")
        ctx = PROFILES.get(prof, PROFILES["balanced"])["ctx"] or 4096
        msgs = self._trim(messages, ctx)
        temp = float(cfg().get("temperature", 0.6) if temperature is None
                     else temperature)

        if cfg().get("backend") == "ollama":
            url = self.base + "/api/chat"
            body = {"model": cfg()["ollama_model"], "messages": msgs, "stream": True,
                    "options": {"temperature": temp, "num_ctx": ctx,
                                "num_gpu": PROFILES.get(prof, {}).get("ngl", 99)}}
        else:
            url = self.base + "/v1/chat/completions"
            body = {"model": "anya", "messages": msgs, "stream": True,
                    "temperature": temp, "cache_prompt": True}

        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        t0 = time.time()
        text, tokens = [], 0
        with urllib.request.urlopen(req, timeout=900) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                    if line == "[DONE]":
                        break
                try:
                    obj = json.loads(line)
                except Exception:                                 # noqa: BLE001
                    continue
                if "error" in obj:
                    raise RuntimeError(str(obj["error"]))
                if "message" in obj:                              # ollama
                    piece = obj["message"].get("content", "")
                    if obj.get("done"):
                        tokens = obj.get("eval_count", tokens)
                else:                                             # openai
                    ch = (obj.get("choices") or [{}])[0]
                    piece = (ch.get("delta") or {}).get("content", "") or ""
                    if obj.get("usage"):
                        tokens = obj["usage"].get("completion_tokens", tokens)
                if piece:
                    text.append(piece)
                    on_token(piece)

        elapsed = max(time.time() - t0, 0.001)
        full = "".join(text)
        if not tokens:
            tokens = max(len(full) // 4, 1)
        tps = tokens / elapsed
        self.last_tps = tps
        self.record_tps(prof, tps)
        self.last_activity = time.time()
        return {"tokens": tokens, "tps": round(tps, 1), "text": full}

    # -- status -----------------------------------------------------------
    def status(self) -> dict:
        gpu = gpu_stats()
        used, total = ram_used_gb()
        prof = cfg().get("profile", "balanced")
        backend = cfg().get("backend", "llama")
        running = self.healthy() if backend == "llama" else True
        measured = cfg().get("measured", {})
        profiles = {}
        for key, p in PROFILES.items():
            m = measured.get(key, {})
            est = estimate_for_model(p["ngl"], p["ctx"]) if not p["stop"] else {"vram_mb": 0, "ram_mb": 0}
            profiles[key] = {
                "label": p["label"],
                "ngl": p["ngl"], "ctx": p["ctx"], "threads": p["threads"],
                "vram_mb": m.get("vram_mb", est["vram_mb"]),
                "ram_mb": m.get("ram_mb", est["ram_mb"]),
                "tps": m.get("tps", ESTIMATES.get(key, {}).get("tps", 0)),
                "measured": m.get("source") == "log",
            }
        cur = measured.get(prof, {})
        return {
            "backend": backend,
            "profile": prof,
            "profiles": profiles,
            "running": bool(running),
            "starting": self.starting,
            "start_error": self.start_error,
            "model": Path(str(cfg()["gguf"])).name,
            "gguf": str(cfg()["gguf"]),
            "gpu_name": gpu["name"],
            "gpu_used_mb": gpu["used_mb"],
            "gpu_total_mb": gpu["total_mb"],
            "gpu_anya_mb": self.own_vram_mb() or cur.get("vram_mb", 0),
            "anya_ram_mb": 0 if PROFILES.get(prof, {}).get("stop") else cur.get("ram_mb", 0),
            "ram_used_gb": used,
            "ram_total_gb": total,
            "last_tps": self.last_tps,
            "idle_unload_min": cfg().get("idle_unload_min", 0),
            "system_prompt": cfg().get("system_prompt", SYSTEM_PROMPT),
            "default_system_prompt": SYSTEM_PROMPT,
            "temperature": cfg().get("temperature", 0.6),
            "web_enabled": bool(cfg().get("web_enabled", False)),
            "web_max_pages": int(cfg().get("web_max_pages", 3)),
            "web_chars": int(cfg().get("web_chars", 1400)),
            "projects_enabled": projects_enabled(),
            "projects_root": str(cfg().get("projects_root") or projects.root()),
            "projects": _projects_status(),
            "library_enabled": library_enabled(),
            "library_recall": bool(cfg().get("library_recall", True)),
            "library_root": str(cfg().get("library_root") or learn.root()),
            "github_token_set": bool(str(cfg().get("github_token") or "").strip()),
            "library": _library_status(),
            "site_enabled": bool(cfg().get("site_enabled", True)),
            "site_repo": cfg().get("site_repo", "SeanTheGoon67/SeanTheGoon67.github.io"),
            "site_branch": cfg().get("site_branch", "main"),
            "site_dir": cfg().get("site_dir", str(PROJECT / "site")),
            "site_use_html": bool(cfg().get("site_use_html", True)),
            "ui_theme": str(cfg().get("ui_theme") or "midnight"),
            "ui_accent": str(cfg().get("ui_accent") or ""),
            "models_dir": str(cfg().get("models_dir") or ""),
            "model": model_info(cfg().get("gguf")),
            "models": _models_status(),
            "max_ngl": active_layers(),
            "memory": _memory_status(),
            "gh_path": cfg().get("gh_path", r"C:\\Users\\Administrator\\AppData\\Local\\Temp\\ghbin\\bin\\gh.exe"),
            "uptime_s": int(time.time() - self.started_at) if self.started_at else 0,
        }


BACKEND = Backend()


def kill_stray_anya_servers() -> None:
    """Kill llama-server processes serving *our* GGUF (never Ollama's own).

    Ollama's bundled llama-server is also called llama-server.exe, so we only
    match processes whose command line names one of *our* model files.
    """
    names = set()
    for d in model_dirs():
        try:
            names.update(p.name for p in d.glob("*.gguf"))
        except Exception:                                             # noqa: BLE001
            pass
    names.add(Path(str(cfg().get("gguf") or "")).name)
    names.discard("")
    if not names:
        return
    match = " -or ".join(
        "$_.CommandLine -like '*%s*'" % n.replace("'", "''") for n in sorted(names))
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='llama-server.exe'\" |"
          f" Where-Object {{ {match} }} |"
          " ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=25,
                       creationflags=0x08000000)
    except Exception:                                             # noqa: BLE001
        pass


def idle_watchdog() -> None:
    """Unload the model after N minutes of silence, if the user asked for it."""
    while True:
        time.sleep(30)
        try:
            mins = int(cfg().get("idle_unload_min", 0) or 0)
            if mins <= 0 or BACKEND.starting:
                continue
            if BACKEND.proc and (time.time() - BACKEND.last_activity) > mins * 60:
                BACKEND.stop()
        except Exception:                                         # noqa: BLE001
            pass


def _search_block(query: str, results: list) -> str:
    """The text Anya reads after a search — the only web she gets to use."""
    lines = [f'Web search results for "{query}":', ""]
    for i, r in enumerate(results, 1):
        lines.append(f'{i}. {r["title"]}')
        lines.append(f'   {r["url"]}')
        if r["snippet"]:
            lines.append(f'   {r["snippet"]}')
    lines += ["", "Answer the user using ONLY these results, in your own words, and "
                  "cite the links you used. If they don't answer the question, say so "
                  "plainly instead of guessing."]
    return "\n".join(lines)


def _log_exc(where: str) -> None:
    """Append the current traceback to the log dir so a failed turn leaves a record.

    Best-effort: a logging failure must never be the thing that breaks a reply.
    """
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with (LOG_DIR / "anya-ui-errors.log").open("a", encoding="utf-8") as fh:
            fh.write(f"\n===== {stamp} [{where}] =====\n")
            fh.write(traceback.format_exc())
    except Exception:                                             # noqa: BLE001
        pass


def _tag_fences(text: str) -> str:
    """Add a language tag to a bare ``` fence when the code makes it obvious.

    The 1.5B model usually labels its fences but not always; an unlabelled fence
    renders with a plain "code" header. This only fills in a tag the source did
    not have, judging from the code itself, so nothing is ever overwritten.
    """
    if "```" not in text:
        return text
    parts = text.split("```")
    # text "A```B```C" -> [A, B, C]: each B/C part starts with what follows the
    # fence, i.e. an optional language tag then the body. Only the *opening*
    # fences (even indices from 1) carry a tag; closing fences are whole parts.
    if len(parts) < 3:
        return text
    out = [parts[0]]
    for idx in range(1, len(parts)):
        part = parts[idx]
        out.append("```")
        if idx % 2 == 1:                     # an opening fence: may need a tag
            head, sep, body = part.partition("\n")
            if head.strip():
                out.append(part)             # already tagged — keep it as-is
            else:
                lang = _guess_lang(body)
                out.append((lang + "\n" if lang else "\n") + body)
        else:
            out.append(part)                 # text after a closing fence
    return "".join(out)


def _guess_lang(code: str) -> str:
    """A best-effort language tag for a code block, or "" when unsure."""
    c = code or ""
    tests = (
        ("kotlin", r"\b(?:fun\s+\w+\s*\(|val\s+\w+\s*[:=]|data class|suspend fun|"
                   r"package\s+com\.|import\s+kotlin|@Composable)\b"),
        ("python", r"(?m)^\s*(?:def|class)\s+\w+.*:\s*$|^\s*import\s+\w+\s*$|"
                   r"^\s*from\s+\w+\s+import|\bprint\s*\(|\bself\b"),
        ("json", r'^\s*[\{\[][\s\S]*[\}\]]\s*$'),
        ("bash", r"(?m)^\s*(?:\$|>)\s*\w|^\s*(?:cd|ls|git|pip|npm|gradle)\s"),
        ("xml", r"^\s*<\?xml|^\s*<[a-zA-Z][\w:.-]*\s"),
        ("java", r"\b(?:public|private)\s+(?:static\s+)?(?:class|void|int|String)\b"),
        ("javascript", r"\b(?:const|let|var)\s+\w+\s*=|=>|console\.log"),
    )
    for name, pat in tests:
        try:
            if re.search(pat, c, re.M):
                return name
        except re.error:                                          # noqa: BLE001
            continue
    return ""


def _sources_block(text: str, sources: list) -> str:
    """A short Sources list for the links Anya was actually given.

    She is asked to cite them herself; anything she left out is added here so a
    reply is never unsourced, and so the links survive in the saved history.
    """
    fresh, seen = [], set()
    for s in sources:
        url = s.get("url") or ""
        if not url or url in seen or url in text:
            continue
        seen.add(url)
        fresh.append((s.get("title") or url, url))
    if not fresh:
        return ""
    lines = "\n".join(f"- [{t}]({u})" for t, u in fresh[:6])
    head = "\n\n" if text.strip() else ""
    return f"{head}**Sources**\n{lines}\n"


def _extract_json(text: str) -> tuple:
    """Scan a brace-balanced JSON object at the start of `text`.

    Returns (the object, index just past its '}'), or (None, -1) while the object
    is still incomplete. Braces inside strings are ignored, so a query containing
    '{' does not confuse it.
    """
    if not text.startswith("{"):
        return None, -1
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[:i + 1], i + 1
    return None, -1


_FENCE = re.compile(r"^\s*`{1,3}(?:json|js|javascript)?\s*$", re.I)
_FENCE_WORD = re.compile(r"^`{0,3}[acijnoprstv]{0,10}$")


def _is_fence_prefix(s: str) -> bool:
    """True while `s` could still grow into a ```` ```json ` fence line."""
    return bool(_FENCE_WORD.match(s.strip()))


# Looks like the opening of a tool object, so an over-long buffer should keep
# waiting rather than be dumped on screen: a write_file call carries a whole
# file in it and is easily longer than a sentence.
_TOOL_HINT = re.compile(r'"(?:name|tool|action|arguments|args|params)"\s*:')

# A name+"arguments" shape, valid JSON or not. The 1.5B model likes to invent
# tools on coding questions ({"name": "json_parse", "arguments": {"code": """..."""}})
# and writes pseudo-JSON that json.loads rejects — so the shape is checked by hand.
_TOOL_SHAPE = re.compile(
    r'"(?:name|tool|action)"\s*:\s*"[A-Za-z_][A-Za-z0-9_.\-]{0,39}"'
    r'[\s\S]{0,80}?"(?:arguments|args|params|parameters|input)"', re.I)

# Another malformation the model writes: the tool name as a bare first token,
# e.g. {"web_search", "query": "latest Android version"} — no "name" key at all.
# It is not valid JSON, so the parsers miss it and it used to reach the screen.
# Matched only when the bare word is a tool-ish name, so ordinary prose JSON
# like {"title", "body"} is not swallowed by accident.
_TOOL_BARE = re.compile(
    r'^\s*\{\s*"((?:web|project|new|build|write|read|list|run|recall|learn|'
    r'site|memory|task|file|dir|apk|search|open)[A-Za-z0-9_.\-]{0,30})"\s*,'
    r'[\s\S]{0,200}?"[A-Za-z_][A-Za-z0-9_]*"\s*:', re.I)


def _project_brief(pid: str, goal: str, step: int, last: str, nudge: str = "") -> str:
    """The state of one project, as a single turn of the unattended loop sees it."""
    proj = projects.get_project(pid)
    tasks = proj.get("tasks", [])
    order = {"doing": 0, "todo": 1, "done": 2}
    tasks = sorted(tasks, key=lambda t: order.get(str(t.get("status", "todo")), 1))
    lb = proj.get("last_build") or {}
    build = ("never built" if not lb.get("ts")
             else ("built ok" if lb.get("ok") else "the last build FAILED"))
    return (
        f"[Autopilot — step {step}.\n"
        f"Project: {proj.get('name', pid)} ({pid}) at {proj.get('path', '')}\n"
        f"Goal: {goal or 'make real progress and get it to build'}\n"
        f"Tasks:\n{_tasks_text(tasks)}\n"
        f"Files:\n{_files_text(pid)}\n"
        f"Build: {build}\n"
        f"Your previous step: {last or '(none yet)'}\n"
        + (f"IMPORTANT: {nudge}\n" if nudge else "")
        + "Take the NEXT single step now. Reply with ONLY one JSON tool object, or "
        '{"name": "finish"} when the goal is met.]'
    )


def _tasks_text(tasks: list) -> str:
    if not tasks:
        return "(no tasks yet)"
    return "\n".join(f"- [{t.get('status', 'todo')}] {t.get('title', '')}" for t in tasks)


def _files_text(pid: str) -> str:
    files = projects.list_files(pid)
    if not files:
        return "(empty)"
    shown = "\n".join(f"- {f['path']}" for f in files[:40])
    if len(files) > 40:
        shown += f"\n(and {len(files) - 40} more)"
    return shown


def _build_block(res: dict) -> str:
    """The compact report handed back to Anya after a build she didn't ask for."""
    apk = res.get("apk") or {}
    if res.get("ok"):
        return (f"[The APK built successfully just now: {apk.get('path', '')} "
                f"({apk.get('bytes', 0) // 1024} KB). Tell the user it is ready, and "
                "what to do next. Don't start another build unless something failed.]")
    return ("[The APK build just failed. Read the tail below and either fix the file it "
            "names or tell the user plainly what is wrong.\n"
            + (res.get("output") or "")[-3000:] + "]")


_SEARCH_NOISE = frozenset({
    "a", "an", "the", "what", "whats", "is", "are", "was", "of", "for", "to",
    "in", "on", "and", "or", "please", "me", "current", "currently", "now",
})


def _search_key(query: str) -> str:
    """A cache key that treats near-identical searches as the same one.

    The model tends to re-ask with a leading article ("the latest version of
    python" after "latest version of python"), which a plain lowercase compare
    misses — so the user sees the whole search run twice. Dropping filler words
    collapses those into one key.
    """
    words = re.findall(r"[a-z0-9]+", (query or "").lower())
    kept = [w for w in words if w not in _SEARCH_NOISE]
    return " ".join(kept or words)


def _query_label(text: str, words: int = 8) -> str:
    """A short label for a tool event, so a long question does not flood the feed."""
    bits = (text or "").split()
    return " ".join(bits[:words]) + ("…" if len(bits) > words else "")


def _library_block(man: dict) -> str:
    """Told to Anya after a repo is read into her library."""
    return (f"[A repository was just read into your local library: "
            f"{man.get('owner', '')}/{man.get('repo', '')}@{man.get('ref', '')} — "
            f"{man.get('files', 0)} text files. It is now on disk and you can search "
            'it with {"name": "recall", "arguments": {"query": "..."}}. Reply with a '
            "short, friendly sentence saying you have read it and are ready — do NOT "
            "start a project or write any files for this.]")


def _recall_block(hits: list, max_chars: int = 5000) -> str:
    """The file excerpts handed to Anya when she (or the app) searched the library.

    Bounded on purpose: a handful of whole files can be thousands of tokens and
    would push a small profile past its context window, so the excerpts share a
    fixed budget and each is trimmed to fit.
    """
    header = ("[From your local library of saved repos — the files below are real, and "
              "are the only source of truth you have for them. Answer from them, quote "
              "them, write code consistent with them, and never invent file contents.]")
    hits = list(hits or [])
    if not hits:
        return header
    parts = [header]
    per = max(600, (max_chars - len(header)) // len(hits))
    for h in hits:
        text = h.get("text", "") or ""
        if len(text) > per:
            text = text[:per] + "\n…[excerpt trimmed]"
        parts.append(f"\n--- {h.get('repo', '')} · {h.get('path', '')} ---\n{text}")
    return "\n".join(parts)


def projects_enabled() -> bool:
    """Whether Anya may create projects, write files and run builds."""
    return bool(cfg().get("projects_enabled", True))


# Housing / real-estate talk is simply not what Anya is for. Detecting it up front
# keeps the model from hallucinating Zillow-style content or dragging library files
# into a question that has nothing to do with code.
_OFF_TOPIC = re.compile(
    r"\b(zillow|realtor\.?com|trulia|redfin|real[\s-]?estate|rental|mortgage|listing"
    r"|listings|apartment|apartments|landlord|tenant|for\s+sale|bedroom|condo"
    r"|housing|house|houses|home\s+price|buy\s+a\s+home|rent\s+(a\s+)?)\b",
    re.I,
)


def is_off_topic(message: str) -> bool:
    """True when the message is about housing/real estate — out of Anya's scope."""
    return bool(_OFF_TOPIC.search(message or ""))


_CODE_HINT = re.compile(
    r"\b(code|class|function|method|file|repo|repository|project|build|gradle"
    r"|kotlin|java|python|android|compose|app|api|import|variable|function"
    r"|error|compile|syntax|implement|debug|readme|module|script)\b",
    re.I,
)

# Something that reads like a question or a request for information, rather than
# a statement about the user. Recall is for "where is X?" questions, not for
# "my name is Robin and I like dark themes" — which merely happens to contain
# the word "app".
_ASK_HINT = re.compile(
    r"\?|\b(how|what|where|why|which|who|does|do you|can you|could you|would you"
    r"|find|show me|look ?up|search|example|examples|usage|signature|where is"
    r"|tell me|explain)\b",
    re.I,
)

# First-person facts about the speaker. If one of these is present and there is
# no actual question, the message is conversation, not a code lookup.
_PERSONAL = re.compile(
    r"\b(my name is|i'?m called|call me|i (?:really )?(?:like|love|prefer|enjoy"
    r"|hate|dislike)|i (?:am|'m) (?:working on|building|based in|living in|from)"
    r"|i live in|i work)\b",
    re.I,
)


def _wants_code_context(message: str) -> bool:
    """Whether a message plausibly needs the saved repos pulled into context.

    Keyword recall is cheap but noisy: without this gate, a stray word makes the
    app shove unrelated file excerpts into a question about something else — or
    answer a personal statement like a repo search.
    """
    msg = message or ""
    if not _CODE_HINT.search(msg):
        return False
    if not _ASK_HINT.search(msg) and _PERSONAL.search(msg):
        return False
    return True

# "write me a data class", "give me a hello world" — the user wants code produced
# right now, not a tour of the saved repos or a fresh Gradle project. When this
# matches, Anya answers directly instead of reaching for a tool.
_WRITE_CODE = re.compile(
    r"\b(write|show|give|make|create|generate|paste|print|return|snippet)\b"
    r".{0,60}\b(code|class|data class|function|method|hello world|example|snippet"
    r"|program|script|kotlin|java|python|app|function|loop|variable|component)\b"
    r"|\b(code|class|data class|function|method|hello world|example|snippet)\b"
    r".{0,40}\b(block|for me|please|in kotlin|in java|in python)\b",
    re.I,
)


def wants_direct_code(message: str) -> bool:
    """True when the user just wants Anya to write/show code on the spot."""
    return bool(_WRITE_CODE.search(message or ""))


# --- what a tool call has to be justified by --------------------------------
# A 1.5B model with no real function-calling will invent tool calls on ordinary
# questions: it answers "explain coroutines" with a web_open to a GitHub URL, or
# "write a data class" with a write_file into whatever project is open, or a
# web_search whose query is the literal placeholder "…". Those used to run and
# wreck the reply. So a tool is only acted on when the user's own words asked for
# that kind of work. When they didn't, she is nudged to answer in plain text.

# A "work on my app" question needs a project noun *and* a verb that acts on it.
_PROJECT_NOUN = re.compile(
    r"\b(app|application|project|apk|android|kotlin|java|gradle|compose|screen"
    r"|layout|activity|button|widget|ui|module|file|files|code|build|emulator"
    r"|manifest|theme|icon|repo|repository|bug|error|crash|test|tests)\b",
    re.I,
)
_PROJECT_VERB = re.compile(
    r"\b(add|adding|change|changing|edit|update|modify|fix|fixing|create|creating"
    r"|make|making|write|writing|build|building|rebuild|run|running|install"
    r"|remove|delete|rename|move|refactor|implement|improve|redesign|replace"
    r"|start|continue|finish|polish|list|show|open|test|launch|generate|scaffold"
    r"|crash|crashes|crashing|broke|broken|fails|failing|debug|troubleshoot)\b",
    re.I,
)


def _wants_web_tools(message: str) -> bool:
    """Whether this message lets the model reach the internet itself.

    Either she was asked to search ("search the web for X", "what's the latest
    version") or the user pasted a link worth opening.
    """
    return web.wants_search(message) or bool(web.find_urls(message, limit=2))


def _wants_project_tools(message: str) -> bool:
    """Whether this message is about working on a project or app."""
    msg = message or ""
    # "make me an app called X" / "build the apk" are project work even though
    # they also trip the "write me code" pattern — check them first.
    if projects.wants_build(msg) or projects.new_project_name(msg):
        return True
    if wants_direct_code(msg):
        return False          # a one-off code block, not the open project
    return bool(_PROJECT_NOUN.search(msg) and _PROJECT_VERB.search(msg))


# "Where is X in my code?" wording — the sign the user means *their saved code*
# rather than a general question that merely mentions a language.
_RECALL_INTENT = re.compile(
    r"(?i)\b(find|search|look\s?up|where(?:'s| is| are| did)|locate|show me"
    r"|my (?:code|repo|repos|project|projects|library|files|file|source|sources)"
    r"|the (?:repo|repos|library|files|source)|saved (?:code|repo|repos|files)"
    r"|in my (?:repo|repos|code|project|library)|from (?:my|the) (?:repo|library)"
    r"|we (?:wrote|have)|did i (?:write|save))\b")


def _wants_library_tools(message: str) -> bool:
    """Whether this message should search or read the saved repos."""
    msg = message or ""
    if learn.wants_repo(msg):
        return True
    if web.wants_search(msg):
        return False          # a live-info question is for the web, not the library
    # Automatic recall is for "where in my saved code is X". A general
    # "explain coroutines" question is not a repo lookup: dumping an unrelated
    # Kotlin file on a 1.5B model just makes it repeat the file instead of
    # answering. So recall needs a sign the user means their own saved code.
    return _wants_code_context(msg) and bool(_RECALL_INTENT.search(msg))


def _tool_allowed(name: str, web_ok: bool, proj_ok: bool, lib_ok: bool) -> bool:
    """Whether one model-emitted tool call is justified by this turn's message."""
    if name in ("web_search", "web_open"):
        return web_ok
    if name in ("recall", "learn_repo"):
        return lib_ok
    return proj_ok           # every other tool is a project action


def library_enabled() -> bool:
    """Whether Anya may read GitHub repos into her library and recall them."""
    return bool(cfg().get("library_enabled", True))


def memory_enabled() -> bool:
    """Whether Anya may remember durable facts about the user."""
    return bool(cfg().get("memory_enabled", True))


def _memory_status() -> dict:
    """A compact Memory block for /api/status, which the GUI polls every 5s."""
    try:
        facts = memory.load()
        return {
            "enabled": memory_enabled(),
            "learn": bool(cfg().get("memory_learn", True)),
            "root": str(memory.root()),
            "count": len(facts),
            "facts": facts[-40:],
        }
    except Exception as exc:                                      # noqa: BLE001
        return {"enabled": False, "count": 0, "facts": [], "error": str(exc)}


def _ask_model_for_facts(prompt: str) -> str:
    """One quiet, low-temperature completion used only for memory extraction."""
    if not BACKEND.healthy():
        return ""
    msgs = [
        {"role": "system", "content": "You extract durable facts about a user. "
                                      "Reply with only a JSON array of short sentences."},
        {"role": "user", "content": prompt},
    ]
    return BACKEND.stream(msgs, lambda *_: None, temperature=0.1,
                          nonblocking=True).get("text", "")


def _learn_async(user_text: str, assistant_text: str) -> None:
    """Learn from one exchange without keeping the reply waiting."""
    if not (memory_enabled() and cfg().get("memory_learn", True)):
        return
    if len(user_text or "") < 12:
        return

    def work() -> None:
        try:
            memory.learn_from_exchange(user_text, assistant_text,
                                       ask_model=_ask_model_for_facts)
        except Exception:                                         # noqa: BLE001
            pass

    threading.Thread(target=work, daemon=True, name="anya-memory").start()


def _models_status() -> list:
    """Compact model list for /api/status — small enough to poll every 5s."""
    try:
        return list_models()
    except Exception:                                             # noqa: BLE001
        return []


def select_model(path_str: str) -> dict:
    """Switch the active .gguf, retune the profiles for it, and reload."""
    p = Path(str(path_str or "").strip())
    if not p.is_file() or p.suffix.lower() != ".gguf":
        raise RuntimeError(f"not a model file: {path_str}")
    with _cfg_lock:
        _config["gguf"] = str(p)
        _config["measured"] = {}          # old footprints belong to the old model
    retune_profiles(active_layers())
    save_config()
    prof = str(cfg().get("profile", "balanced"))
    BACKEND.stop()
    kill_stray_anya_servers()
    if PROFILES.get(prof, {}).get("stop"):
        return {"ok": True, "applying": False, "profile": prof, "model": model_info(p)}
    res = BACKEND.apply(prof)
    res["model"] = model_info(p)
    return res


def _library_status() -> dict:
    """A compact Library block for /api/status, which the GUI polls every 5s."""
    try:
        items = learn.list_repos()
        used = sum(int(r.get("bytes") or 0) for r in items)
        return {
            "root": str(learn.root()),
            "count": len(items),
            "files": sum(int(r.get("files") or 0) for r in items),
            "bytes": used,
            "repos": items[:20],
            "recent": items[0]["id"] if items else "",
        }
    except Exception as exc:                                      # noqa: BLE001
        return {"error": str(exc), "repos": [], "count": 0, "files": 0, "bytes": 0}


def _projects_status() -> dict:
    """A compact Projects block for /api/status, which the GUI polls every 5s."""
    try:
        pid = projects.current()
        items = projects.list_projects()
        if not pid and items:
            pid = items[0]["id"]
        block: dict = {
            "root": str(projects.root()),
            "current": pid,
            "count": len(items),
            "projects": items[:20],
            "activity": projects.activity(),
            "feed": projects.feed()[-8:],
            "approvals": len(projects.list_approvals()),
        }
        if pid:
            try:
                proj = projects.get_project(pid)
                block["current_project"] = {
                    "id": proj["id"], "name": proj["name"], "kind": proj["kind"],
                    "status": proj.get("status", "active"),
                    "tasks": proj.get("tasks", []),
                    "last_build": proj.get("last_build") or {},
                    "path": proj["path"],
                }
            except projects.ProjectError:
                pass
        return block
    except Exception as exc:                                      # noqa: BLE001
        return {"error": str(exc), "projects": [], "count": 0}


def _any_tool(text: str) -> "dict | None":
    """A web, project or library tool call - whichever this text contains."""
    return (web.parse_tool_call(text) or projects.parse_tool_call(text)
            or learn.parse_tool_call(text))


def _looks_like_tool(obj) -> bool:
    """True for any small JSON object shaped like a tool call.

    Anya's 1.5B model sometimes hallucinates tool names that aren't real
    (e.g. a fake 'listings_near' housing call). Those are plumbing, not prose,
    and must never reach the screen. This catches the *shape*: a short object
    with a "name" (or "tool"/"action") string plus an arguments-ish payload.

    `obj` arrives as the raw JSON text from `_extract_json`; it is parsed here.
    """
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except Exception:                                         # noqa: BLE001
            # Pseudo-JSON the model often writes (triple-quoted strings, raw
            # newlines): fall back to a shape test so a fake tool can't leak.
            return bool(_TOOL_SHAPE.search(obj))
    if not isinstance(obj, dict):
        return False
    name = obj.get("name") or obj.get("tool") or obj.get("action")
    if not isinstance(name, str) or not name.strip() or len(name) > 40:
        return False
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.\-]*", name.strip()):
        return False
    arg_keys = ("arguments", "args", "params", "parameters", "input")
    has_args = any(k in obj for k in arg_keys)
    # Objects built only from tool-result plumbing keys (files/content/text/...)
    # are the model echoing results back — never real prose.
    plumbing_keys = {"files", "content", "text", "result", "output", "data",
                     "error", "response", "path", "ok", "listing", "entries",
                     "message", "name", "detail", "query", "url", "repo"}
    if obj and all(k in plumbing_keys for k in obj):
        return True
    # `{"name": "x"}` with nothing else is plumbing; a big object is prose/JSON data.
    return has_args or len(obj) <= 3


def _tool_key(call: dict) -> str:
    """A stable identity for one tool call, so a repeat can be spotted."""
    try:
        return json.dumps(call, sort_keys=True, default=str)
    except Exception:                                             # noqa: BLE001
        return repr(call)


class _ReplyFilter:
    """Streams model output while never letting a JSON tool call reach the screen.

    Anya has no real function-calling: she asks for the web by writing one small
    JSON object. Usually it is the whole reply, but she sometimes puts a sentence
    in front of it ("Let me open that page:") — so this watches for the object
    wherever it appears, swallows it (with any code fence around it) if it names a
    tool, and streams everything else through untouched.
    """

    def __init__(self, emit) -> None:
        self._emit = emit
        self._buf = ""
        self.emitted = False
        self._after_call = False

    def feed(self, piece: str) -> None:
        self._buf += piece
        while self._buf:
            brace = self._buf.find("{")
            if brace < 0:
                if _is_fence_prefix(self._buf):
                    return                      # maybe the start of a fenced call
                self._out(self._buf)
                self._buf = ""
                return
            prefix = self._buf[:brace]
            # text before the brace is safe unless it is only whitespace/fence
            if prefix and not _FENCE.match(prefix):
                self._out(prefix)
                self._buf = self._buf[brace:]
                continue
            rest = self._buf[brace:]
            shape = bool(_TOOL_SHAPE.search(rest[:400])) \
                or bool(_TOOL_BARE.match(rest[:240]))
            obj, end = _extract_json(rest)
            if end >= 0 and (_any_tool(obj) or _looks_like_tool(obj)):
                self._buf = rest[end:]          # a tool call — swallow it
                self._after_call = True
                continue
            if shape:
                # A tool-shaped object we can't parse cleanly (the model's
                # pseudo-JSON). Hold it: flush() drops it instead of dumping the
                # raw JSON on screen. This is the "json_parse leak".
                return
            if end >= 0 or (len(rest) > 800 and not _TOOL_HINT.search(rest[:240])):
                # not a tool call (or far too long to be one): show it
                cut = end if end >= 0 else 1
                self._out(prefix + rest[:cut])
                self._buf = rest[cut:]
                continue
            return                              # incomplete — wait for more pieces

    def flush(self) -> None:
        """End of stream: release anything left, unless it was meant as plumbing."""
        left, self._buf = self._buf, ""
        if not left:
            return
        if self._after_call:                    # a fence closing the swallowed call
            left = re.sub(r"\s*`{1,3}\s*$", "", left)
            if not left:
                return
        probe = re.sub(r"^\s*`{1,3}(?:json|js|javascript)?\s*", "", left).lstrip()
        if probe.startswith("{"):
            return                              # an unfinished tool call — drop it
        self._out(left)

    def _out(self, text: str) -> None:
        if text:
            self.emitted = True
            self._after_call = False
            self._emit(text)


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------

_UNLOCK_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Anya</title>
<style>
 body{margin:0;height:100vh;display:grid;place-items:center;background:#0b0c10;color:#e8eaf0;
      font-family:-apple-system,"Segoe UI",Roboto,sans-serif}
 .box{max-width:340px;padding:28px;background:#12141b;border:1px solid #232733;border-radius:16px;text-align:center}
 h1{margin:0 0 6px;font-size:19px}p{margin:0 0 18px;color:#8a92a6;font-size:14px;line-height:1.5}
 input{width:100%;box-sizing:border-box;padding:11px 13px;border-radius:10px;border:1px solid #2d3342;
       background:#171a23;color:#e8eaf0;font-size:15px;outline:none}
 button{margin-top:12px;width:100%;padding:11px;border:none;border-radius:10px;cursor:pointer;
        background:linear-gradient(135deg,#7c5cff,#6d4dfa);color:#fff;font-size:15px;font-weight:600}
</style></head><body><form class="box" method="get" action="/">
 <h1>Anya is locked</h1>
 <p>This copy is shared on your network. Paste the access key from the desktop app to continue.</p>
 <input name="k" placeholder="access key" autofocus autocomplete="off">
 <button type="submit">Unlock</button>
</form></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "AnyaUI/1.0"
    protocol_version = "HTTP/1.1"

    # builds finished during the current chat turn, keyed by project id, so the
    # model can't trigger the same Gradle build twice in one reply
    _turn_builds: dict | None = None

    def _remember_build(self, pid: str, res: dict) -> None:
        if self._turn_builds is None:
            self._turn_builds = {}
        self._turn_builds[pid] = res

    # -- helpers ----------------------------------------------------------
    def log_message(self, fmt, *args):        # quiet
        pass

    def _json(self, obj, code: int = 200) -> None:
        payload = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _text(self, text: str, code: int = 200, ctype: str = "text/plain; charset=utf-8") -> None:
        payload = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _raw_body(self) -> bytes:
        """Raw request body, drained exactly once (same keep-alive rule as _body)."""
        cached = getattr(self, "_raw_obj", None)
        if cached is not None:
            return cached
        n = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(n) if n else b""
        self._raw_obj = data
        return data

    def _body(self) -> dict:
        """Read and cache the request body, so nothing is left in the socket.

        Every POST drains the body exactly once: a handler that ignores it would
        otherwise leave bytes in the pipe and corrupt the next keep-alive request.
        Raw (non-JSON) posts like the mic's WAV arrive here too, so the bytes are
        cached once and shared with _raw_body() instead of being read twice.
        """
        cached = getattr(self, "_body_obj", None)
        if cached is not None:
            return cached
        data = self._raw_body()
        obj: dict = {}
        if data:
            try:
                obj = json.loads(data.decode("utf-8"))
            except Exception:                                     # noqa: BLE001
                obj = {}
        if not isinstance(obj, dict):
            obj = {}
        self._body_obj = obj
        return obj

    def _wav(self, data: bytes, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _sse_open(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def _sse(self, obj: dict) -> None:
        self.wfile.write(f"data: {json.dumps(obj)}\n\n".encode("utf-8"))
        self.wfile.flush()

    # -- access control (phone access) ------------------------------------
    def _via_proxy(self) -> bool:
        """True when the request came through the Cloudflare tunnel.

        cloudflared connects to us from 127.0.0.1, so `_from_localhost()` alone
        would treat the whole public internet as local.  A quick tunnel always
        adds at least one of these headers; a direct browser hit on this machine
        does not.
        """
        for h in ("Cf-Connecting-Ip", "CF-Connecting-IP", "Cf-Ray",
                  "X-Forwarded-For", "X-Forwarded-Proto"):
            if self.headers.get(h):
                return True
        return False

    def _from_localhost(self) -> bool:
        # anything arriving through the tunnel is never "this PC", no matter
        # what loopback address cloudflared used to reach us
        if self._via_proxy():
            return False
        ip = (self.client_address[0] if self.client_address else "") or ""
        if ip not in ("127.0.0.1", "::1", "localhost", ""):
            return False
        # a loopback peer with a public Host header means something is forwarding
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        if host and host not in ("127.0.0.1", "localhost", "::1", "[::1]"):
            return False
        return True

    def _given_key(self) -> str:
        hdr = self.headers.get("X-Anya-Key") or ""
        if hdr:
            return hdr.strip()
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "anya_key":
                return v.strip()
        if "?" in self.path:
            q = urllib.parse.parse_qs(self.path.split("?", 1)[1])
            return (q.get("k") or [""])[0]
        return ""

    def _authorised(self) -> bool:
        """Open to this PC; a phone needs the shared key when remote access is on."""
        if not cfg().get("remote_enabled"):
            return True
        if self._from_localhost():
            return True
        return self._given_key() == remote_token()

    def _deny(self, path: str) -> None:
        if path.startswith("/api/"):
            return self._json({"error": "unauthorized", "need_key": True}, 401)
        return self._text(_UNLOCK_HTML, 401, "text/html; charset=utf-8")

    def _maybe_set_key_cookie(self) -> bool:
        """If the URL carried the key, remember it and clean the address bar."""
        if self._from_localhost() or "?" not in self.path:
            return False
        q = urllib.parse.parse_qs(self.path.split("?", 1)[1])
        if (q.get("k") or [""])[0] != remote_token():
            return False
        keep = [(k, v) for k, vals in q.items() if k != "k" for v in vals]
        clean = self.path.split("?", 1)[0]
        if keep:
            clean += "?" + urllib.parse.urlencode(keep)
        self.send_response(302)
        self.send_header("Location", clean)
        self.send_header("Set-Cookie",
                         f"anya_key={remote_token()}; Path=/; Max-Age=31536000; SameSite=Lax")
        self.send_header("Content-Length", "0")
        self.end_headers()
        return True

    # -- routes -----------------------------------------------------------
    def do_GET(self) -> None:                                     # noqa: N802
        path = self.path.split("?")[0]
        try:
            if path != "/api/health" and not self._authorised():
                return self._deny(path)
            if self._maybe_set_key_cookie():
                return
            if path in ("/", "/index.html"):
                if not INDEX_HTML.exists():
                    return self._text("index.html missing", 500)
                return self._text(INDEX_HTML.read_text(encoding="utf-8"),
                                  200, "text/html; charset=utf-8")

            if path in ("/anya.ico", "/favicon.ico"):
                ico = PROJECT / "anya.ico"
                if ico.exists():
                    body = ico.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/x-icon")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "max-age=86400")
                    self.end_headers()
                    return self.wfile.write(body)
                return self._json({"error": "no icon"}, 404)

            if path in ("/anya.png", "/anya-avatar.png"):
                png = PROJECT / "anya.png"
                if png.exists():
                    body = png.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "max-age=86400")
                    self.end_headers()
                    return self.wfile.write(body)
                return self._json({"error": "no avatar"}, 404)

            if path == "/api/status":
                st = BACKEND.status()
                st["version"] = anya_version()
                st["remote"] = remote_status()
                st["update"] = updater.cached()
                st["phone_app"] = phone_status()
                return self._json(st)

            if path == "/api/health":
                return self._json({"ok": True, "version": anya_version()})

            if path == "/api/remote":
                return self._json(remote_status())

            if path == "/api/remote/qr.png":
                q = {}
                if "?" in self.path:
                    q = urllib.parse.parse_qs(self.path.split("?", 1)[1])
                url = (q.get("url") or [""])[0] or remote_status()["phone_url"]
                try:
                    scale = max(3, min(14, int((q.get("scale") or ["6"])[0])))
                except Exception:                                 # noqa: BLE001
                    scale = 6
                try:
                    png = qr.png(url, scale=scale, border=4)
                except Exception as exc:                          # noqa: BLE001
                    return self._json({"error": f"qr failed: {exc}"}, 400)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(png)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return self.wfile.write(png)

            if path == "/api/update":
                q = {}
                if "?" in self.path:
                    q = urllib.parse.parse_qs(self.path.split("?", 1)[1])
                force = (q.get("force") or ["0"])[0] in ("1", "true", "yes")
                return self._json(updater.check(str(cfg().get("github_token") or ""),
                                                force=force))

            if path == "/api/version":
                return self._json({"version": anya_version()})

            if path == "/api/phone-app":
                return self._json(phone_status())

            if path in ("/anya-phone.apk", "/api/phone-app/apk"):
                apk = phoneapp.published_apk()
                if not apk or not apk.exists():
                    return self._json(
                        {"error": "no APK built yet - press Build in the Phone app "
                                  "section of Settings"}, 404)
                body = apk.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type",
                                 "application/vnd.android.package-archive")
                self.send_header("Content-Disposition",
                                 'attachment; filename="anya-phone.apk"')
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return self.wfile.write(body)

            if path == "/api/phone-app/qr.png":
                # a QR pointing straight at the APK, so the phone can scan and
                # install without typing anything
                q = {}
                if "?" in self.path:
                    q = urllib.parse.parse_qs(self.path.split("?", 1)[1])
                try:
                    scale = max(3, min(14, int((q.get("scale") or ["6"])[0])))
                except Exception:                                 # noqa: BLE001
                    scale = 6
                url = phone_apk_url()
                if not url:
                    return self._json({"error": "phone access is off, so there is "
                                                "no URL for a phone to reach"}, 400)
                try:
                    png = qr.png(url, scale=scale, border=4)
                except Exception as exc:                          # noqa: BLE001
                    return self._json({"error": f"qr failed: {exc}"}, 400)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(png)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return self.wfile.write(png)

            if path == "/api/sessions":
                q = ""
                if "?" in self.path:
                    q = urllib.parse.parse_qs(self.path.split("?", 1)[1]).get("q", [""])[0]
                return self._json({"sessions": list_sessions(q)})

            m = re.match(r"^/api/sessions/([0-9a-f]+)$", path)
            if m:
                s = get_session(m.group(1))
                return self._json(s) if s else self._json({"error": "not found"}, 404)

            m = re.match(r"^/api/export/([0-9a-f]+)$", path)
            if m:
                md = export_markdown(m.group(1))
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="anya-{m.group(1)}.md"')
                body = md.encode("utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)

            if path == "/api/projects":
                return self._json({"projects": projects.list_projects(),
                                   "root": str(projects.root()),
                                   "current": projects.current()})

            if path == "/api/approvals":
                return self._json({"approvals": projects.list_approvals()})

            m = re.match(r"^/api/projects/([A-Za-z0-9._-]+)/file$", path)
            if m:
                rel = ""
                if "?" in self.path:
                    q = urllib.parse.parse_qs(self.path.split("?", 1)[1])
                    rel = (q.get("path") or [""])[0]
                try:
                    return self._json(projects.read_file(m.group(1), rel))
                except projects.ProjectError as exc:
                    return self._json({"error": str(exc)}, 404)

            m = re.match(r"^/api/projects/([A-Za-z0-9._-]+)$", path)
            if m:
                try:
                    return self._json(projects.get_project(m.group(1)))
                except projects.ProjectError as exc:
                    return self._json({"error": str(exc)}, 404)

            if path == "/api/library":
                return self._json(_library_status())

            m = re.match(r"^/api/library/([A-Za-z0-9._-]+)/file$", path)
            if m:
                rel = ""
                if "?" in self.path:
                    q = urllib.parse.parse_qs(self.path.split("?", 1)[1])
                    rel = (q.get("path") or [""])[0]
                try:
                    return self._json(learn.read_file(m.group(1), rel))
                except learn.LearnError as exc:
                    return self._json({"error": str(exc)}, 404)

            m = re.match(r"^/api/library/([A-Za-z0-9._-]+)$", path)
            if m:
                try:
                    return self._json(learn.get_repo(m.group(1)))
                except learn.LearnError as exc:
                    return self._json({"error": str(exc)}, 404)

            if path == "/api/site":
                try:
                    return self._json(site_tools.status(cfg()))
                except Exception as exc:                              # noqa: BLE001
                    return self._json({"error": str(exc)}, 500)

            if path == "/api/site/read":
                try:
                    return self._json(site_tools.read(cfg()))
                except Exception as exc:                              # noqa: BLE001
                    return self._json({"error": str(exc)}, 500)

            if path == "/api/voice":
                st = voice.status()
                st["stt"] = bool(cfg().get("voice_stt", True))
                st["tts"] = bool(cfg().get("voice_tts", False))
                st["stt_model"] = cfg().get("voice_stt_model", "small.en")
                st["piper_voice"] = cfg().get("voice_piper_voice",
                                              "en_US-lessac-medium")
                return self._json(st)

            if path == "/api/models":
                try:
                    return self._json({"models": list_models()})
                except Exception as exc:                              # noqa: BLE001
                    return self._json({"error": str(exc)}, 500)

            if path == "/api/memory":
                return self._json(_memory_status())

            return self._json({"error": "no such route"}, 404)
        except Exception as exc:                                  # noqa: BLE001
            return self._json({"error": str(exc)}, 500)

    def do_DELETE(self) -> None:                                  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/api/sessions":
            return self._json({"ok": True, "deleted": clear_all_sessions()})
        m = re.match(r"^/api/sessions/([0-9a-f]+)$", path)
        if m:
            delete_session(m.group(1))
            return self._json({"ok": True})
        m = re.match(r"^/api/projects/([A-Za-z0-9._-]+)$", path)
        if m:
            try:
                projects.delete_project(m.group(1))
            except projects.ProjectError as exc:
                return self._json({"error": str(exc)}, 400)
            return self._json({"ok": True})
        m = re.match(r"^/api/library/([A-Za-z0-9._-]+)$", path)
        if m:
            try:
                learn.delete_repo(m.group(1))
            except learn.LearnError as exc:
                return self._json({"error": str(exc)}, 400)
            return self._json({"ok": True})
        m = re.match(r"^/api/memory/([0-9a-f]+)$", path)
        if m:
            ok = memory.remove(m.group(1))
            return self._json({"ok": ok, "facts": memory.load()})
        return self._json({"error": "no such route"}, 404)

    # -- projects ----------------------------------------------------------
    def build_project(self, pid: str) -> None:
        """Build an APK, streaming the Gradle log to the browser as it arrives."""
        try:
            proj = projects.get_project(pid)
        except projects.ProjectError as exc:
            return self._json({"error": str(exc)}, 404)
        self._sse_open()
        self._sse({"type": "build_start", "project": pid, "name": proj.get("name", pid)})
        try:
            res = projects.build_apk(pid, on_line=lambda line: self._sse(
                {"type": "log", "text": line}))
        except projects.ProjectError as exc:
            return self._sse({"type": "build_done", "ok": False, "error": str(exc)})
        except Exception as exc:                                  # noqa: BLE001
            return self._sse({"type": "build_done", "ok": False, "error": str(exc)})
        self._sse({"type": "build_done", "ok": bool(res.get("ok")),
                   "code": res.get("code"), "duration_s": res.get("duration_s"),
                   "apk": res.get("apk") or {},
                   "output": (res.get("output") or "")[-4000:]})

    # -- library -----------------------------------------------------------
    def fetch_library(self) -> None:
        """Read a whole GitHub repo into the library, streaming progress to the UI."""
        body = self._body()
        repo = str(body.get("repo") or "").strip()
        if not repo:
            return self._json({"error": "no repository given"}, 400)

        self._sse_open()
        self._sse({"type": "lib_start", "repo": repo})
        try:
            man = learn.fetch_repo(repo, on_event=self._library_log)
        except learn.LearnError as exc:
            return self._sse({"type": "lib_done", "ok": False, "error": str(exc)})
        except Exception as exc:                                  # noqa: BLE001
            return self._sse({"type": "lib_done", "ok": False, "error": str(exc)})
        self._sse({"type": "lib_done", "ok": True, "id": man.get("id"),
                   "owner": man.get("owner"), "repo": man.get("repo"),
                   "ref": man.get("ref"), "files": man.get("files"),
                   "bytes": man.get("bytes")})

    def build_phone_app(self) -> None:
        """Build the Anya phone APK and stream the log to the browser.

        This runs Gradle through `projects.run`, so the build shares the exact
        environment and allow-list the Projects sandbox already uses. The APK is
        published next to the app and served at /anya-phone.apk.
        """
        if phoneapp._build_lock.locked():
            return self._json({"error": "an APK build is already running"}, 409)
        self._sse_open()
        self._sse({"type": "apk_start", "ts": time.time()})
        try:
            with phoneapp._build_lock:
                res = phoneapp.build(
                    on_line=lambda line: self._sse({"type": "apk_line", "line": line}),
                    key=remote_token())
        except Exception as exc:                                  # noqa: BLE001
            self._sse({"type": "apk_done", "ok": False, "error": str(exc)})
            return
        self._sse({"type": "apk_done", "ok": bool(res.get("ok")),
                   "apk": res.get("apk", ""), "bytes": res.get("bytes", 0),
                   "code": res.get("code"),
                   "download_url": phone_apk_url(),
                   "qr_url": "/api/phone-app/qr.png",
                   "error": "" if res.get("ok") else "build failed"})

    def auto_project(self, pid: str) -> None:
        """Work a project unattended, one small step at a time.

        Each turn the model sees the project's real state (tasks, files, last
        build, its own previous step) and is asked for a single tool call. The
        call is run through the same sandbox as chat, the result becomes the next
        turn's context, and the whole thing streams to the browser. It stops when
        she says she is done, repeats a step, the step budget runs out, or the
        user closes the stream.
        """
        body = self._body()
        goal = str(body.get("goal") or "").strip()
        try:
            max_steps = max(1, min(20, int(body.get("steps") or 8)))
        except (TypeError, ValueError):
            max_steps = 8

        try:
            proj = projects.get_project(pid)
        except projects.ProjectError as exc:
            return self._json({"error": str(exc)}, 404)

        if cfg().get("backend") == "llama":
            if PROFILES.get(cfg().get("profile", "balanced"), {}).get("stop"):
                return self._json({"error": "Anya is switched off."}, 409)
            if not BACKEND.healthy():
                return self._json({"error": "Anya's model isn't running."}, 409)

        self._sse_open()
        self._sse({"type": "auto_start", "project": pid,
                   "name": proj.get("name", pid), "goal": goal, "max": max_steps})

        system = (cfg().get("system_prompt", SYSTEM_PROMPT) + PROJECTS_PROMPT
                  + AUTOPILOT_PROMPT)
        seen: dict = {}
        reason, step, last, nudge, repeats = "budget", 0, "", "", 0
        try:
            for step in range(1, max_steps + 1):
                try:
                    projects.get_project(pid)          # deleted mid-run?
                except projects.ProjectError:
                    reason = "gone"
                    break
                brief = _project_brief(pid, goal, step, last, nudge)
                msgs = [{"role": "system", "content": system},
                        {"role": "user", "content": brief}]
                self._sse({"type": "step", "n": step})
                text, _tokens, _tps = self._generate(msgs, lambda s: self._sse(
                    {"type": "token", "text": s}))
                call = _any_tool(text)
                if not call:
                    last = (text or "").strip()[:200]
                    if nudge:                      # already nudged once — she is done
                        reason = "finished"
                        break
                    nudge = ("You replied without a tool call. If the goal is met, "
                             'reply with {"name": "finish"}. Otherwise reply with '
                             "ONE JSON tool object now.")
                    continue
                if str(call.get("name", "")) == "finish":
                    reason = "finished"
                    break
                call["project"] = pid              # an unattended run is about *this* project
                key = _tool_key(call)
                if seen.get(key):                  # she is going round in circles
                    repeats += 1
                    if repeats >= 2:
                        self._sse({"type": "note",
                                   "text": "She kept repeating a step, so I stopped."})
                        reason = "repeated"
                        break
                    nudge = ("You already did that exact step — repeating it will not "
                             "help. Take a DIFFERENT step: edit another file, add a "
                             'task, or reply {"name": "finish"} if it is really done.')
                    continue
                seen[key] = 1
                nudge = ""
                result = self._run_project_tool(call)
                last = f"{call.get('name')}: {result[:200]}"
                self._sse({"type": "result", "text": (result or "")[:1200]})
        except Exception as exc:                                  # noqa: BLE001
            try:
                self._sse({"type": "auto_done", "ok": False, "steps": step,
                           "reason": "error", "error": str(exc)})
            except Exception:                                     # noqa: BLE001
                pass
            return
        self._sse({"type": "auto_done", "ok": True, "steps": step,
                   "reason": reason, "goal": goal})

    def do_POST(self) -> None:                                    # noqa: N802
        path = self.path.split("?")[0]
        self._body()            # always drain the body so keep-alive stays in sync
        try:
            if not self._authorised():
                return self._deny(path)
            if path == "/api/chat":
                return self.chat()
            if path == "/api/profile":
                body = self._body()
                return self._json(BACKEND.apply(str(body.get("profile", ""))))
            if path == "/api/sessions":
                body = self._body()
                return self._json({"id": new_session(body.get("title") or "New chat")})
            if path == "/api/settings":
                body = self._body()
                with _cfg_lock:
                    if "system_prompt" in body:
                        _config["system_prompt"] = str(body["system_prompt"])
                    if "idle_unload_min" in body:
                        _config["idle_unload_min"] = int(body["idle_unload_min"])
                    if "temperature" in body:
                        _config["temperature"] = float(body["temperature"])
                    if "backend" in body:
                        _config["backend"] = str(body["backend"])
                    if "web_enabled" in body:
                        _config["web_enabled"] = bool(body["web_enabled"])
                    if "web_max_pages" in body:
                        _config["web_max_pages"] = max(1, min(6, int(body["web_max_pages"])))
                    if "web_chars" in body:
                        _config["web_chars"] = max(400, min(6000, int(body["web_chars"])))
                    if "projects_enabled" in body:
                        _config["projects_enabled"] = bool(body["projects_enabled"])
                    if "projects_root" in body:
                        new_root = str(body["projects_root"]).strip()
                        if new_root:
                            _config["projects_root"] = new_root
                            projects.set_root(new_root)
                    if "library_enabled" in body:
                        _config["library_enabled"] = bool(body["library_enabled"])
                    if "library_recall" in body:
                        _config["library_recall"] = bool(body["library_recall"])
                    if "library_root" in body:
                        new_root = str(body["library_root"]).strip()
                        if new_root:
                            _config["library_root"] = new_root
                            learn.set_root(new_root)
                    if "github_token" in body:
                        _config["github_token"] = str(body["github_token"]).strip()
                        learn.set_token(_config["github_token"])
                    if "ui_theme" in body:
                        _config["ui_theme"] = str(body["ui_theme"]).strip() or "midnight"
                    if "ui_accent" in body:
                        _config["ui_accent"] = str(body["ui_accent"]).strip()
                    if "voice_stt" in body:
                        _config["voice_stt"] = bool(body["voice_stt"])
                    if "voice_tts" in body:
                        _config["voice_tts"] = bool(body["voice_tts"])
                    if "voice_stt_model" in body:
                        _config["voice_stt_model"] = str(body["voice_stt_model"]).strip() or "small.en"
                    if "voice_piper_voice" in body:
                        _config["voice_piper_voice"] = str(body["voice_piper_voice"]).strip() or "en_US-lessac-medium"
                    if "voice_device" in body:
                        _config["voice_device"] = str(body["voice_device"]).strip().lower() or "cpu"
                        voice.configure(_config["voice_device"])
                    if "memory_enabled" in body:
                        _config["memory_enabled"] = bool(body["memory_enabled"])
                    if "memory_learn" in body:
                        _config["memory_learn"] = bool(body["memory_learn"])
                    if "memory_dir" in body:
                        new_dir = str(body["memory_dir"]).strip()
                        if new_dir:
                            _config["memory_dir"] = new_dir
                            memory.configure(new_dir)
                    if "memory_inject" in body:
                        _config["memory_inject"] = max(5, min(120, int(body["memory_inject"])))
                    if "custom" in body:
                        _config["custom"] = body["custom"]
                save_config()
                if body.get("apply_custom"):
                    p = _config["custom"]
                    PROFILES["custom"] = {"label": "Custom", "ngl": int(p.get("ngl", 24)),
                                          "ctx": int(p.get("ctx", 4096)),
                                          "threads": int(p.get("threads", 0)), "stop": False}
                    if _config["profile"] == "custom":
                        return self._json(BACKEND.apply("custom"))
                return self._json({"ok": True})
            if path == "/api/projects":
                body = self._body()
                try:
                    proj = projects.new_project(
                        str(body.get("name") or "New project"),
                        kind=str(body.get("kind") or "android"),
                        description=str(body.get("description") or ""))
                except projects.ProjectError as exc:
                    return self._json({"error": str(exc)}, 400)
                return self._json(proj)

            if path == "/api/phone-app/build":
                return self.build_phone_app()

            m = re.match(r"^/api/projects/([A-Za-z0-9._-]+)/task$", path)
            if m:
                body = self._body()
                pid = m.group(1)
                try:
                    if body.get("task_id"):
                        return self._json(projects.set_task(
                            pid, str(body["task_id"]), str(body.get("status") or "todo")))
                    return self._json(projects.add_task(
                        pid, str(body.get("title") or ""), str(body.get("status") or "todo")))
                except projects.ProjectError as exc:
                    return self._json({"error": str(exc)}, 400)

            m = re.match(r"^/api/projects/([A-Za-z0-9._-]+)/current$", path)
            if m:
                try:
                    projects.get_project(m.group(1))
                except projects.ProjectError as exc:
                    return self._json({"error": str(exc)}, 404)
                projects.set_current(m.group(1))
                return self._json({"ok": True, "current": projects.current()})

            m = re.match(r"^/api/projects/([A-Za-z0-9._-]+)/build$", path)
            if m:
                return self.build_project(m.group(1))

            m = re.match(r"^/api/projects/([A-Za-z0-9._-]+)/auto$", path)
            if m:
                return self.auto_project(m.group(1))

            m = re.match(r"^/api/projects/([A-Za-z0-9._-]+)/reveal$", path)
            if m:
                try:
                    p = projects.reveal(m.group(1))
                except projects.ProjectError as exc:
                    return self._json({"error": str(exc)}, 404)
                return self._json({"ok": True, "path": p})

            if path == "/api/library":
                return self.fetch_library()

            if path == "/api/library/export-all":
                try:
                    return self._json(learn.export_dataset(None))
                except learn.LearnError as exc:
                    return self._json({"error": str(exc)}, 400)

            m = re.match(r"^/api/library/([A-Za-z0-9._-]+)/export$", path)
            if m:
                try:
                    return self._json(learn.export_dataset(m.group(1)))
                except learn.LearnError as exc:
                    return self._json({"error": str(exc)}, 400)

            m = re.match(r"^/api/library/([A-Za-z0-9._-]+)/reveal$", path)
            if m:
                try:
                    p = learn.reveal(m.group(1))
                except learn.LearnError as exc:
                    return self._json({"error": str(exc)}, 404)
                return self._json({"ok": True, "path": p})

            if path == "/api/site/save":
                body = self._body()
                try:
                    res = site_tools.write(cfg(), md=body.get("md"), html=body.get("html"), build_html=True)
                    return self._json(res)
                except Exception as exc:                              # noqa: BLE001
                    return self._json({"error": str(exc)}, 400)

            if path == "/api/site/pull":
                ok, msg = site_tools.pull(cfg())
                return self._json({"ok": ok, "message": msg})

            if path == "/api/site/push":
                body = self._body()
                ok, msg = site_tools.push(cfg(), message=str(body.get("message") or "Update site"))
                return self._json({"ok": ok, "message": msg})

            m = re.match(r"^/api/approvals/([A-Za-z0-9._-]+)$", path)
            if m:
                body = self._body()
                try:
                    return self._json(projects.resolve_approval(
                        m.group(1), bool(body.get("approve"))))
                except projects.ProjectError as exc:
                    return self._json({"error": str(exc)}, 404)

            m = re.match(r"^/api/sessions/([0-9a-f]+)/rename$", path)
            if m:
                rename_session(m.group(1), str(self._body().get("title", "")))
                return self._json({"ok": True})

            if path == "/api/memory":
                body = self._body()
                if body.get("clear"):
                    n = memory.clear()
                    return self._json({"ok": True, "forgot": n, "facts": []})
                text = body.get("text") or body.get("facts") or []
                added = memory.add(text, source="you")
                return self._json({"ok": True, "added": added, "facts": memory.load()})

            if path == "/api/models/select":
                body = self._body()
                try:
                    return self._json(select_model(str(body.get("path") or "")))
                except Exception as exc:                              # noqa: BLE001
                    return self._json({"error": str(exc)}, 400)

            if path == "/api/voice/stt":
                # raw 16 kHz mono PCM WAV straight from the browser's mic
                if not cfg().get("voice_stt", True):
                    return self._json({"error": "the mic is switched off in Settings"}, 403)
                audio = self._raw_body()
                try:
                    text = voice.transcribe(
                        audio, model=str(cfg().get("voice_stt_model", "small.en")))
                except voice.VoiceError as exc:
                    return self._json({"error": str(exc)}, 400)
                return self._json({"text": text})

            if path == "/api/remote":
                body = self._body()
                restart = False
                with _cfg_lock:
                    if "enabled" in body:
                        want = bool(body["enabled"])
                        if want != bool(_config.get("remote_enabled")):
                            restart = True
                        _config["remote_enabled"] = want
                        _config["host"] = "0.0.0.0" if want else "127.0.0.1"
                    if "remote_tunnel_on_start" in body:
                        _config["remote_tunnel_on_start"] = bool(body["remote_tunnel_on_start"])
                    if "tunnel" in body:
                        _config["remote_tunnel"] = str(body["tunnel"]) or "off"
                    if "discovery" in body:
                        _config["remote_discovery"] = bool(body["discovery"])
                    if body.get("rotate_token"):
                        import secrets
                        _config["remote_token"] = secrets.token_urlsafe(9)
                    tunnel = _config.get("remote_tunnel", "off")
                    want_disc = bool(_config.get("remote_discovery", True))
                    remote_on = bool(_config.get("remote_enabled"))
                save_config()
                if "tunnel" in body or body.get("rotate_token"):
                    if tunnel == "cloudflare":
                        remote.start_tunnel(int(cfg().get("port", 8091)))
                    else:
                        remote.stop_tunnel()
                if "discovery" in body:
                    if want_disc and remote_on:
                        remote.start_discovery(int(cfg().get("port", 8091)))
                    else:
                        remote.stop_discovery()
                res = remote_status()
                res["restart_required"] = restart
                if restart and body.get("restart", True):
                    res["restarting"] = True
                    restart_soon()
                return self._json(res)

            if path == "/api/remote/tunnel":
                body = self._body()
                action = str(body.get("action") or "")
                if action == "install":
                    try:
                        path_to = remote.download_cloudflared()
                        return self._json({"ok": True, "path": path_to})
                    except Exception as exc:                      # noqa: BLE001
                        return self._json({"ok": False, "error": str(exc)}, 400)
                if action == "start":
                    return self._json(remote.start_tunnel(int(cfg().get("port", 8091))))
                if action == "stop":
                    return self._json(remote.stop_tunnel())
                return self._json(remote.tunnel_status())

            if path == "/api/update/apply":
                body = self._body()
                res = updater.apply(str(cfg().get("github_token") or ""))
                if res.get("ok") and body.get("restart", True):
                    res["restarting"] = True
                    restart_soon(1.8)
                return self._json(res)

            if path == "/api/restart":
                restart_soon()
                return self._json({"ok": True, "restarting": True})

            return self._json({"error": "no such route"}, 404)
        except Exception as exc:                                  # noqa: BLE001
            return self._json({"error": str(exc)}, 500)

    # -- chat -------------------------------------------------------------
    def chat(self) -> None:
        body = self._body()
        message = (body.get("message") or "").strip()
        if not message:
            return self._json({"error": "empty message"}, 400)

        sid = body.get("session_id") or new_session()
        if not get_session(sid):
            sid = new_session()

        profile = cfg().get("profile", "balanced")
        if cfg().get("backend") == "llama":
            if PROFILES.get(profile, {}).get("stop"):
                return self._json(
                    {"error": "Anya is switched off. Turn on a power profile first."}, 409)
            if not BACKEND.healthy():
                if BACKEND.starting:
                    return self._json(
                        {"error": "Anya is still waking up — give it a moment."}, 409)
                return self._json(
                    {"error": "Anya's model isn't running. Pick a power profile."}, 409)

        add_message(sid, "user", message)

        web_on = bool(cfg().get("web_enabled", False))
        proj_on = projects_enabled()
        lib_on = library_enabled()
        system = cfg().get("system_prompt", SYSTEM_PROMPT)
        if web_on:
            system = system + WEB_PROMPT
        if proj_on:
            system = system + PROJECTS_PROMPT
        # Only teach the library protocol when this message could plausibly be
        # about saved code. A 1.5B model left holding the recall tool will fire it
        # at "my name is Robin and I like dark themes" merely because the word
        # "app" appeared, and answer a personal note like a repo search.
        if lib_on and (_wants_code_context(message) or learn.wants_repo(message)):
            system = system + LIBRARY_PROMPT
        if memory_enabled():
            block = memory.context_block(message,
                                         int(cfg().get("memory_inject", 30) or 30))
            if block:
                system = system + block

        history = get_session(sid)["messages"]
        msgs = [{"role": "system", "content": system}]
        msgs += [{"role": m["role"], "content": m["content"]} for m in history]

        self._sse_open()
        self._sse({"type": "start", "session_id": sid})

        streamed: list[str] = []
        fences = {"n": 0}

        def emit(piece: str) -> None:
            streamed.append(piece)
            fences["n"] += piece.count("```")
            self._sse({"type": "token", "text": piece})

        # Housing / real-estate prompts are simply outside Anya's scope. Answer
        # deterministically so the 1.5B model never gets the chance to hallucinate
        # Zillow-style listings, prices, or property data.
        if is_off_topic(message):
            reply = ("I don't deal with housing, rentals, listings, or real estate — "
                     "that's not what I'm for. I'm Anya, a coding and Android assistant "
                     "running on your PC. Ask me about code, building an app, or just "
                     "chat with me and I'll be glad to help.")
            emit(reply)
            mid = add_message(sid, "assistant", reply, 0, 0, profile)
            self._sse({"type": "done", "session_id": sid, "message_id": mid,
                       "tokens": 0, "tps": 0.0,
                       "title": (get_session(sid) or {}).get("title", "")})
            return

        sources: list[dict] = []
        cache: dict = {"search": {}, "open": {}, "fail": {}, "builds": {}}
        # shared for this turn: the prefetch records a build here, and the tool
        # loop reads it so a second build_apk is answered, not re-run
        self._turn_builds = cache["builds"]
        # Only the work the user's own words justify. A 1.5B model invents tool
        # calls on ordinary questions ("write me a data class" -> a write_file
        # into the open project), so these flags decide both which prefetch runs
        # and which model-emitted tool call is allowed to act.
        web_ok = web_on and _wants_web_tools(message)
        proj_ok = proj_on and _wants_project_tools(message)
        lib_ok = lib_on and not wants_direct_code(message) \
            and _wants_library_tools(message)
        tools_on = web_ok or proj_ok or lib_ok
        try:
            if web_ok:
                self._safe_prefetch(
                    "web", lambda: self._prefetch(msgs, message, sources, cache))
            if proj_ok:
                self._safe_prefetch(
                    "projects", lambda: self._project_prefetch(msgs, message))
            if lib_ok:
                self._safe_prefetch(
                    "library", lambda: self._library_prefetch(msgs, message))

            rounds = (int(cfg().get("web_max_pages", 3)) if web_ok else 0) \
                + (12 if proj_ok else 0) \
                + (4 if lib_ok else 0)
            seen: dict = {}
            nudged_fake = False
            while True:
                # Always run output through the filter so a stray tool-shaped JSON
                # object can never leak to the screen, but only act on one when
                # this message justified it.
                text, tokens, tps = self._generate(msgs, emit)
                call = _any_tool(text) if tools_on else None
                if call and not _tool_allowed(call.get("name", ""),
                                              web_ok, proj_ok, lib_ok):
                    # Not justified by this question — do not run it. Nudge once
                    # for a plain answer; if she does it again, stop and fall back.
                    if nudged_fake:
                        break
                    nudged_fake = True
                    msgs.append({"role": "assistant", "content": text})
                    msgs.append({"role": "user", "content":
                                 "(That tool is not relevant to this question and you "
                                 "must not call it. Do not call any tool at all now. "
                                 "Answer the user directly in plain text.)"})
                    continue
                if not call:
                    # The filter showed an ordinary answer — unless it swallowed a
                    # *hallucinated* tool call (a fake name the app can't run), in
                    # which case nothing was emitted. Nudge once so she answers plainly.
                    if (text.strip() and not "".join(streamed).strip()
                            and not nudged_fake):
                        nudged_fake = True
                        msgs.append({"role": "assistant", "content": text})
                        msgs.append({"role": "user", "content":
                                     "(That was not a real tool — you have no such tool. "
                                     "Do not call tools. Answer the user's request directly "
                                     "in plain text now.)"})
                        continue
                    break                 # an ordinary answer — the filter showed it
                key = _tool_key(call)
                seen[key] = seen.get(key, 0) + 1
                if rounds <= 0 or seen[key] > 1:
                    # Out of budget, or she is repeating herself: stop and make her answer.
                    note = ("(You have already run that tool call. Stop calling tools "
                            "and answer the user now, using what you already have.)"
                            if rounds > 0 else
                            "(You've used all your tool calls for this reply. Answer "
                            "the user now, using what you already have.)")
                    msgs.append({"role": "assistant", "content": text})
                    msgs.append({"role": "user", "content": note})
                    text, tokens, tps = self._generate(msgs, emit)
                    break
                rounds -= 1
                msgs.append({"role": "assistant", "content": text})
                msgs.append({"role": "user",
                             "content": self._safe_tool(call, sources, cache)})

            # Persist exactly what was shown, not the raw model output: a tool
            # call the filter swallowed must not reappear in the history.
            # If the reply stopped inside a code block, close the fence so the
            # rest of the chat doesn't render as code.
            if fences["n"] % 2:
                emit("\n```")
            visible = "".join(streamed)
            if not visible.strip():
                # The model emitted only a (possibly hallucinated) tool call that
                # the filter swallowed. Give the user a real, on-topic reply
                # instead of an empty bubble.
                visible = ("I'm not sure how to help with that one. I'm a coding "
                           "and Android assistant — ask me about code, apps, or "
                           "just chat with me.")
                emit(visible)
            tail = _sources_block(visible, sources)
            if tail:
                emit(tail)
                visible += tail

            # The model doesn't always label its fences; fill in a tag it left
            # out so the finished reply renders with the right header. The UI
            # re-renders from this text on `done`, so send it along.
            tagged = _tag_fences(visible)
            if tagged != visible:
                visible = tagged

            mid = add_message(sid, "assistant", visible, tokens, tps, profile)
            self._sse({"type": "done", "session_id": sid, "message_id": mid,
                       "tokens": tokens, "tps": tps, "text": visible,
                       "title": (get_session(sid) or {}).get("title", "")})
            _learn_async(message, visible)
        except Exception as exc:                                  # noqa: BLE001
            _log_exc("chat")
            partial = "".join(streamed)
            if partial:
                add_message(sid, "assistant", partial, 0, 0, profile)
            self._sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})

    # -- web browsing ------------------------------------------------------
    def _generate(self, msgs: list, emit) -> tuple[str, int, float]:
        """Stream a completion without ever showing a JSON tool call.

        Returns the model's raw text (which chat() then inspects for a tool call);
        the user only ever sees what the filter let through.

        If llama-server rejects the prompt as over its context window (HTTP 400),
        retry once with just the system prompt and the latest turn, so a long
        history can never turn a question into an empty red-boxed reply.
        """
        filt = _ReplyFilter(emit)
        try:
            res = BACKEND.stream(msgs, filt.feed)
        except urllib.error.HTTPError as exc:
            if exc.code != 400 or len(msgs) <= 2 or filt.emitted:
                raise
            _log_exc("generate:ctx-overflow")
            res = BACKEND.stream([msgs[0], msgs[-1]], filt.feed)
        filt.flush()
        return res["text"], res["tokens"], res["tps"]

    def _tool_event(self, state: str, name: str, detail: str = "", ok: bool = True) -> None:
        self._sse({"type": "tool", "state": state, "name": name,
                   "detail": detail, "ok": ok})

    def _safe_prefetch(self, label: str, fn) -> None:
        """Run a deterministic prefetch, but never let it kill the whole reply.

        A prefetch that throws (a tool module raising something other than its
        own error type, a bad URL, a dead socket) used to bubble all the way to
        chat()'s handler and replace the answer with an empty bubble and a red
        box. A failed prefetch is a missing nicety, not a failed turn, so it is
        logged and skipped.
        """
        try:
            fn()
        except Exception:                                         # noqa: BLE001
            _log_exc(f"prefetch:{label}")

    def _safe_tool(self, call: dict, sources: list, cache: dict) -> str:
        """Run a tool call; if it blows up, tell Anya so she still answers."""
        try:
            return self._run_tool(call, sources, cache)
        except Exception as exc:                                  # noqa: BLE001
            _log_exc(f"tool:{call.get('name')}")
            name = call.get("name") or "that tool"
            return (f"The {name} step failed with: {exc}. Tell the user that part "
                    "did not work and answer with what you already know — do not "
                    "invent results.")

    def _fetch_page(self, url: str, sources: list, cache: dict) -> tuple:
        """Open one page, memoised for this turn. Returns (page, error, repeated)."""
        cap = int(cfg().get("web_chars", 1400))
        if url in cache["open"]:      # already shown the user once this turn — stay quiet
            return cache["open"][url], "", False
        if url in cache["fail"]:      # don't hammer a URL that already failed
            return None, cache["fail"][url], True
        self._tool_event("start", "web_open", url)
        try:
            page = web.page_text(url, max_chars=cap)
        except Exception as exc:                                  # noqa: BLE001
            if not isinstance(exc, web.WebError):
                _log_exc(f"web_open:{url}")
            cache["fail"][url] = str(exc)
            self._tool_event("done", "web_open", str(exc), ok=False)
            return None, str(exc), False
        cache["open"][url] = page
        cache["open"][page["url"]] = page
        if not any(s["url"] == page["url"] for s in sources):
            sources.append({"title": page["title"] or page["url"], "url": page["url"]})
        self._tool_event("done", "web_open", (page["title"] or page["url"])[:70])
        return page, "", False

    def _fetch_search(self, query: str, sources: list, cache: dict) -> tuple:
        """Search, memoised for this turn. Returns (results, error, repeated)."""
        key = _search_key(query)
        if key in cache["search"]:    # already shown the user once this turn — stay quiet
            return cache["search"][key], "", False
        if key in cache["fail"]:
            return None, cache["fail"][key], True
        self._tool_event("start", "web_search", query)
        try:
            results = web.search(query, max_results=6)
        except Exception as exc:                                  # noqa: BLE001
            if not isinstance(exc, web.WebError):
                _log_exc(f"web_search:{query}")
            cache["fail"][key] = str(exc)
            self._tool_event("done", "web_search", str(exc), ok=False)
            return None, str(exc), False
        cache["search"][key] = results
        if not results:
            self._tool_event("done", "web_search", "no results", ok=False)
            return [], "", False
        for r in results:
            if not any(s["url"] == r["url"] for s in sources):
                sources.append({"title": r["title"] or r["url"], "url": r["url"]})
        self._tool_event("done", "web_search", f"{len(results)} results")
        return results, "", False

    def _prefetch(self, msgs: list, message: str, sources: list, cache: dict) -> None:
        """The two things that don't depend on Anya choosing to use the tool.

        A link the user pasted is opened, and an explicit "search the web for X" is
        searched, before she is even asked — a 1.5B model left to decide for itself
        will too often answer from memory instead, and get it wrong.
        """
        for url in web.find_urls(message, limit=2):
            if library_enabled() and learn.wants_repo(url):
                continue          # a repo link is better read by the library, below
            page, _, _ = self._fetch_page(url, sources, cache)
            if page:
                msgs.append({"role": "user", "content":
                             "[The user pasted this link. Here is the page itself — "
                             "use only what it actually says]\n"
                             f'{page["url"]}\n{page["title"]}\n\n{page["text"]}'})
        if web.wants_search(message):
            query = web.search_query_from(message)
            results, _, _ = self._fetch_search(query, sources, cache)
            if results:
                msgs.append({"role": "user", "content": _search_block(query, results)})

    def _run_tool(self, call: dict, sources: list, cache: dict) -> str:
        """Run one tool call — web, library or project — and return what Anya reads."""
        name = call.get("name")
        self._turn_builds = cache.setdefault("builds", {})
        if name in ("web_search", "web_open"):
            return self._run_web_tool(call, sources, cache)
        if name in ("recall", "learn_repo"):
            return self._run_library_tool(call)
        return self._run_project_tool(call)

    # -- web tools ---------------------------------------------------------
    def _run_web_tool(self, call: dict, sources: list, cache: dict) -> str:
        """Run one tool call Anya asked for, and return the text she reads next."""
        if call["name"] == "web_search":
            query = call["query"]
            results, err, again = self._fetch_search(query, sources, cache)
            if again:
                return (f'That search ("{query}") has already failed this turn. Do NOT '
                        "try again — tell the user you couldn't search just now.")
            if results is None:
                return (f'The web search for "{query}" failed: {err}. Tell the user '
                        "you couldn't search just now — don't pretend you did.")
            if not results:
                return f'The web search for "{query}" returned nothing at all.'
            return _search_block(query, results)

        url = call["url"]
        page, err, again = self._fetch_page(url, sources, cache)
        if again:
            return (f"{url} has already failed this turn. Do NOT try it again — tell "
                    "the user you couldn't open that page.")
        if page is None:
            return (f"Opening {url} failed: {err}. Tell the user you couldn't open "
                    "that page.")
        return (f'web_open result for {page["url"]}\nTitle: {page["title"]}\n\n'
                f'{page["text"]}\n\n(The page may be cut short. Answer from it.)')

    # -- project tools -----------------------------------------------------
    def _project_prefetch(self, msgs: list, message: str) -> None:
        """The project actions that don't depend on Anya choosing the tool.

        Left to decide for herself, a 1.5B model will too often just *describe*
        what it would do. Saying "make an app called X" creates it, and "build the
        apk" builds the current project, before she is even asked — the same
        deterministic shortcut the web prefetch uses.
        """
        created = None
        name = projects.new_project_name(message)
        if name:
            self._tool_event("start", "new_project", name)
            try:
                created = projects.new_project(name, kind="android")
            except projects.ProjectError as exc:
                self._tool_event("done", "new_project", str(exc), ok=False)
                return
            self._tool_event("done", "new_project", created["name"])
            msgs.append({"role": "user", "content":
                         f"[Project '{created['name']}' was just created at "
                         f"{created['path']}. It already contains a working Android "
                         "scaffold, so it builds as-is. Change a file with write_file, "
                         "then run build_apk.]"})

        # "make an app called X, then build it" must do both, not just the first part
        if not projects.wants_build(message):
            return
        pid = (created or {}).get("id") or projects.current()
        if pid:
            self._tool_event("start", "build_apk", pid)
            try:
                res = projects.build_apk(pid)
            except projects.ProjectError as exc:
                self._tool_event("done", "build_apk", str(exc), ok=False)
                return
            self._remember_build(pid, res)
            apk = res.get("apk") or {}
            self._tool_event("done", "build_apk", apk.get("name") or f"exit {res['code']}",
                             ok=bool(res.get("ok")))
            msgs.append({"role": "user", "content": _build_block(res)})

    # -- library tools -----------------------------------------------------
    def _library_log(self, **k) -> None:
        """Stream a library progress line, ignoring the marker-only events."""
        text = str(k.get("text") or "")
        if not text and k.get("kind") == "progress":
            text = f"… {k.get('files', 0)} files, up to {k.get('path', '')}"
        if text:
            self._sse({"type": "log", "text": text})

    def _library_prefetch(self, msgs: list, message: str) -> None:
        """Read a repo the user named, and hand Anya the files a question needs.

        A pasted GitHub link is read straight away (the deterministic shortcut the
        web and project prefetches use), and when recall is on the app quietly pulls
        the most relevant saved files into context, so a 1.5B model does not have to
        decide for itself to look.
        """
        just_read = False
        spec = learn.wants_repo(message)
        if spec:
            label = f"{spec['owner']}/{spec['repo']}"
            self._tool_event("start", "learn_repo", label)
            try:
                man = learn.fetch_repo(spec, on_event=self._library_log)
            except learn.LearnError as exc:
                self._tool_event("done", "learn_repo", str(exc), ok=False)
            except Exception as exc:                              # noqa: BLE001
                self._tool_event("done", "learn_repo", str(exc), ok=False)
            else:
                self._tool_event("done", "learn_repo",
                                 f"{man['files']} files, {man['bytes'] // 1024} KB")
                msgs.append({"role": "user", "content": _library_block(man)})
                just_read = True

        # A fresh read already gave her the repo, so recalling it again this turn
        # would only bury the point in noise. Skip recall when the message plainly
        # isn't about code — otherwise a stray keyword drags unrelated files in.
        if just_read or not cfg().get("library_recall", True):
            return
        if not _wants_code_context(message):
            return
        try:
            hits = learn.recall(message)
        except Exception:                                         # noqa: BLE001
            hits = []
        if hits:
            self._tool_event("start", "recall", _query_label(message))
            self._tool_event("done", "recall", f"{len(hits)} file(s)")
            msgs.append({"role": "user", "content": _recall_block(hits)})

    def _run_library_tool(self, call: dict) -> str:
        """Carry out one library tool call and describe the result to Anya."""
        name = call.get("name", "")
        if name == "learn_repo":
            repo = str(call.get("repo") or "").strip()
            self._tool_event("start", "learn_repo", repo)
            try:
                man = learn.fetch_repo(repo, on_event=self._library_log)
            except Exception as exc:                              # noqa: BLE001
                if not isinstance(exc, learn.LearnError):
                    _log_exc(f"learn_repo:{repo}")
                self._tool_event("done", "learn_repo", str(exc), ok=False)
                return f"Reading that repo failed: {exc}"
            self._tool_event("done", "learn_repo",
                             f"{man['files']} files, {man['bytes'] // 1024} KB")
            return _library_block(man)

        query = str(call.get("query") or "").strip()
        self._tool_event("start", "recall", _query_label(query))
        try:
            hits = learn.recall(query) if query else []
        except Exception as exc:                                  # noqa: BLE001
            self._tool_event("done", "recall", str(exc), ok=False)
            return f"Searching the library failed: {exc}"
        if not hits:
            self._tool_event("done", "recall", "nothing found", ok=False)
            return ("Nothing in the library matches that. Say plainly that it isn't in "
                    "the saved repos — do not invent file contents.")
        self._tool_event("done", "recall", f"{len(hits)} file(s)")
        return _recall_block(hits)

    def _run_project_tool(self, call: dict) -> str:
        """Carry out one project tool call and describe the result to Anya."""
        name = call.get("name", "")
        pid = str(call.get("project") or projects.current() or "").strip()

        if name == "finish":
            return "Understood — you consider the work finished. Say so to the user."

        if name == "new_project":
            label = call.get("project_name") or "New project"
            self._tool_event("start", "new_project", label)
            try:
                proj = projects.new_project(label, kind=call.get("kind") or "android")
            except projects.ProjectError as exc:
                self._tool_event("done", "new_project", str(exc), ok=False)
                return f"Creating the project failed: {exc}"
            self._tool_event("done", "new_project", proj["name"])
            return (f"Created project '{proj['name']}' (id {proj['id']}) at {proj['path']}. "
                    "It already contains a working Android scaffold. Change a file with "
                    "write_file, then run build_apk.")

        if not pid:
            return ('There is no current project. Create one first, e.g. '
                    '{"name": "new_project", "arguments": {"name": "My App"}}.')
        try:
            proj = projects.get_project(pid)
        except projects.ProjectError as exc:
            return f"That project does not exist ({exc})."

        if name == "write_file":
            rel = str(call.get("path") or "")
            self._tool_event("start", "write_file", rel)
            res = projects.write_or_request(pid, rel, str(call.get("content") or ""))
            if res.get("pending"):
                self._tool_event("done", "write_file", "needs your approval", ok=False)
                return (f"{res['path']} is outside the project, so it is waiting for the "
                        "user to approve it in the Projects tab. Tell them.")
            self._tool_event("done", "write_file", res["path"])
            return f"Wrote {res['bytes']} bytes to {res['path']}."

        if name == "read_file":
            rel = str(call.get("path") or "")
            self._tool_event("start", "read_file", rel)
            try:
                r = projects.read_file(pid, rel)
            except projects.ProjectError as exc:
                self._tool_event("done", "read_file", str(exc), ok=False)
                return f"Reading that file failed: {exc}"
            self._tool_event("done", "read_file", r["path"])
            return f"Contents of {r['path']}:\n\n{r['text']}"

        if name == "list_files":
            self._tool_event("start", "list_files", proj["name"])
            files = projects.list_files(pid)
            self._tool_event("done", "list_files", f"{len(files)} files")
            shown = files[:60]
            listing = "\n".join(f"- {f['path']}" for f in shown)
            more = "" if len(shown) == len(files) else \
                f"\n(and {len(files) - len(shown)} more; don't list again — edit a file, " \
                "or build.)"
            return f"Files in {proj['name']} ({len(files)}):\n{listing}{more}"

        if name == "project_task":
            title = str(call.get("title") or "").strip()
            status = str(call.get("status") or "todo")
            if not title:
                return ('To change the task list, include a title, e.g. {"name": '
                        '"project_task", "arguments": {"title": "Add the button", '
                        '"status": "doing"}}.')
            self._tool_event("start", "project_task", title)
            existing = next((t for t in proj.get("tasks", [])
                             if t.get("title", "").lower() == title.lower()), None)
            if existing:
                projects.set_task(pid, existing["id"], status)
            else:
                projects.add_task(pid, title, status)
            self._tool_event("done", "project_task", title)
            return f"Task '{title}' is now {status}."

        if name == "build_apk":
            # A build already ran this turn (the prefetch does it when the user
            # says "make an app and build it"), so answer from that result instead
            # of running Gradle a second time. The model tends to call build_apk
            # again after reading the "[the APK built]" note it was handed.
            done_build = (self._turn_builds or {}).get(pid)
            if done_build is not None:
                apk = done_build.get("apk") or {}
                if done_build.get("ok"):
                    return (f"The APK is already built from this turn: "
                            f"{apk.get('path')} ({apk.get('bytes', 0) // 1024} KB). "
                            "It can be installed on a phone. Do not build again — "
                            "just tell the user it is ready.")
                return ("A build already ran this turn and FAILED. Do not run it again "
                        "— fix the file the error names with write_file, or tell the "
                        "user plainly what is wrong. The error was:\n\n"
                        + (done_build.get("output") or "")[-2000:])
            self._tool_event("start", "build_apk", proj["name"])
            try:
                res = projects.build_apk(pid)
            except projects.ProjectError as exc:
                self._tool_event("done", "build_apk", str(exc), ok=False)
                return f"Building failed: {exc}"
            if self._turn_builds is not None:
                self._turn_builds[pid] = res
            apk = res.get("apk") or {}
            if res.get("ok"):
                self._tool_event("done", "build_apk", apk.get("name", "APK"))
                return (f"The APK built successfully: {apk.get('path')} "
                        f"({apk.get('bytes', 0) // 1024} KB). It can be installed on a "
                        "phone with adb. Tell the user it is ready.")
            self._tool_event("done", "build_apk", f"failed (exit {res['code']})", ok=False)
            return ("The build FAILED. Here is the tail of the output — find the first "
                    "real error, fix the file it names, then build again:\n\n"
                    + (res.get("output") or ""))

        if name == "run_command":
            cmd = str(call.get("command") or "")
            if re.search(r"(?i)\bgradlew?(?:\.bat)?\b[^\n]*\b(?:assemble|bundle|build)\b", cmd):
                return ('Do not run gradle yourself. Build the APK with '
                        '{"name": "build_apk", "arguments": {}} instead.')
            self._tool_event("start", "run_command", cmd)
            try:
                res = projects.run(pid, cmd)
            except projects.ProjectError as exc:
                self._tool_event("done", "run_command", str(exc), ok=False)
                return f"That command was refused: {exc}"
            self._tool_event("done", "run_command", f"exit {res['code']}", ok=res["ok"])
            return (f"$ {res['cmd']}\n(exit {res['code']} in {res['duration_s']}s)\n\n"
                    + (res.get("output") or "")[-4000:])

        return f"There is no tool called {name!r}."


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def ui_already_running(host: str, port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/status", timeout=2) as r:
            return r.status == 200
    except Exception:                                             # noqa: BLE001
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Anya's chat UI")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--profile", default=None)
    ap.add_argument("--host", default=None)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    load_config()
    retune_profiles(active_layers())
    memory.configure(_config.get("memory_dir"))
    projects.configure(str(ROOT), _config.get("projects_root"))
    learn.configure(str(ROOT), _config.get("library_root"),
                    dataset_dir=PROJECT / "dataset")
    learn.set_token(str(_config.get("github_token") or ""))
    voice.configure(str(_config.get("voice_device") or "cpu"))
    if args.port:
        _config["port"] = args.port
    if args.host:
        _config["host"] = args.host
    if args.profile and args.profile in PROFILES:
        _config["profile"] = args.profile

    host, port = _config["host"], int(_config["port"])
    bind = "0.0.0.0" if _config.get("remote_enabled") else host

    if ui_already_running("127.0.0.1", port):
        print(f"[=] Anya's UI is already running on http://127.0.0.1:{port}")
        if not args.no_open:
            open_browser(f"http://127.0.0.1:{port}")
        return 0

    db_init()
    save_config()

    if _config["backend"] == "llama":
        # Model startup (which also reclaims the port) happens in the background so
        # the UI is reachable immediately and can show a "loading" state.
        threading.Thread(target=lambda: BACKEND.apply(_config["profile"]),
                         daemon=True).start()
    threading.Thread(target=idle_watchdog, daemon=True).start()

    if _config.get("remote_enabled") and _config.get("remote_tunnel_on_start") \
            and _config.get("remote_tunnel") == "cloudflare":
        threading.Thread(target=lambda: (time.sleep(2), remote.start_tunnel(port)),
                         daemon=True).start()

    # answer a phone's UDP probe so it can find this PC without being told the
    # address. Only useful while phone access is on.
    if _config.get("remote_enabled") and _config.get("remote_discovery", True):
        try:
            st = remote.start_discovery(port)
            if not st.get("running"):
                print(f"    (phone auto-discovery off: {st.get('error', '')})")
        except Exception as exc:                                  # noqa: BLE001
            _log_exc("discovery:start")

    httpd = ThreadingHTTPServer((bind, port), Handler)
    httpd.daemon_threads = True
    print(f"[+] Anya's UI  ->  http://127.0.0.1:{port}")
    print(f"    backend={_config['backend']}  profile={_config['profile']}")
    if _config.get("remote_enabled"):
        for u in remote_urls()["lan"]:
            print(f"    phone (this Wi-Fi)  ->  {u}?k={remote_token()}")
    print("    press Ctrl+C to stop the UI (the model is stopped with it)")

    if not args.no_open:
        threading.Thread(target=lambda: (time.sleep(0.6), open_browser(f"http://127.0.0.1:{port}")),
                         daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[.] shutting down")
    finally:
        remote.stop_tunnel()
        BACKEND.stop()
    return 0


def open_browser(url: str) -> None:
    brave = Path(r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe")
    try:
        if brave.exists():
            subprocess.Popen([str(brave), f"--app={url}"], creationflags=0x08000000)
        else:
            import webbrowser
            webbrowser.open(url)
    except Exception:                                             # noqa: BLE001
        pass


if __name__ == "__main__":
    sys.exit(main())
