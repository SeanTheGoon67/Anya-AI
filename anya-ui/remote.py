#!/usr/bin/env python
"""
remote.py — let Anya be reached from a phone (standard library only).

Two ways out of this PC:

  * on your home Wi-Fi, Anya is already reachable at her LAN address once the
    server binds to 0.0.0.0 — we just need to tell you the URL and show a QR;
  * from anywhere else, we can raise a temporary *Cloudflare quick tunnel*
    (no account needed) and hand back the https URL. If Tailscale is installed
    we surface that private address too.

Nothing here talks to the model; it only discovers addresses and, if asked,
runs a tunnel helper process that Anya's UI supervises.
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
TOOLS_DIR = PROJECT / "tools"

_CF_URL = ("https://github.com/cloudflare/cloudflared/releases/latest/download/"
           "cloudflared-windows-amd64.exe")
_CF_RX = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

_lock = threading.Lock()
_tunnel: dict = {"proc": None, "url": "", "error": "", "started": 0.0, "log": []}

_addr_cache: dict = {"at": 0.0, "lan": [], "ts": ""}
_ADDR_TTL = 15.0


# ---------------------------------------------------------------------------
# addresses
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# auto-discovery (so the phone never has to be told the address)
# ---------------------------------------------------------------------------
# The phone broadcasts a one-line UDP probe on this port; we answer with where
# Anya lives. Standard library on both sides — no Bonjour service, no extra
# dependency in the APK.

DISCOVERY_PORT = 8092
_MAGIC = b"ANYA-DISCOVER/1"

_disc = {"sock": None, "thread": None, "running": False, "error": ""}


def _discovery_payload(port: int) -> bytes:
    """What we tell a phone that just asked where Anya is."""
    import json                                             # noqa: PLC0415
    urls = ["http://{}:{}".format(ip, port) for ip in lan_ips()]
    ts = tailscale_ip()
    if ts:
        urls.append("http://{}:{}".format(ts, port))
    tun = tunnel_status()
    if tun.get("running") and tun.get("url"):
        urls.append(str(tun["url"]).rstrip("/"))
    return json.dumps({
        "app": "anya",
        "name": "Anya",
        "port": port,
        "host": socket.gethostname(),
        "urls": urls,
    }).encode("utf-8")


def start_discovery(port: int) -> dict:
    """Listen for phone probes and answer with this PC's Anya URLs. Idempotent."""
    with _lock:
        if _disc["running"]:
            return {"running": True, "port": DISCOVERY_PORT}
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("0.0.0.0", DISCOVERY_PORT))
            sock.settimeout(1.0)
        except OSError as exc:
            if sock:
                sock.close()
            _disc["error"] = str(exc)
            _disc["running"] = False
            return {"running": False, "error": str(exc)}

        def serve() -> None:
            while _disc["running"]:
                try:
                    data, addr = sock.recvfrom(512)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data.startswith(_MAGIC):
                    continue
                try:
                    sock.sendto(_discovery_payload(port), addr)
                except OSError:
                    continue

        _disc.update({"sock": sock, "running": True, "error": "",
                      "thread": threading.Thread(target=serve, daemon=True,
                                                 name="anya-discovery")})
        _disc["thread"].start()
        return {"running": True, "port": DISCOVERY_PORT}


def stop_discovery() -> None:
    with _lock:
        _disc["running"] = False
        sock = _disc.get("sock")
        if sock:
            try:
                sock.close()
            except OSError:
                pass
        _disc["sock"] = None


def discovery_status() -> dict:
    with _lock:
        return {"running": bool(_disc["running"]), "port": DISCOVERY_PORT,
                "error": _disc.get("error", "")}


def lan_ips() -> list:
    """Every usable (non-loopback, non-link-local) IPv4 address on this PC."""
    now = time.time()
    if _addr_cache["lan"] and now - _addr_cache["at"] < _ADDR_TTL:
        return list(_addr_cache["lan"])
    found: set = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if _usable(ip):
                found.add(ip)
    except Exception:                                             # noqa: BLE001
        pass
    # the UDP trick reveals the address that actually routes out (best default)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("1.1.1.1", 80))
            ip = s.getsockname()[0]
            if _usable(ip):
                found.add(ip)
        finally:
            s.close()
    except Exception:                                             # noqa: BLE001
        pass
    # put the routing address first so the plain URL is the likely-good one
    ordered = [ip for ip in found]
    ordered.sort(key=lambda ip: (not ip.startswith("192.168."), ip))
    _addr_cache["lan"] = ordered
    _addr_cache["at"] = now
    return ordered


def _usable(ip: str) -> bool:
    return bool(ip) and not ip.startswith("127.") and not ip.startswith("169.254.")


def primary_ip() -> str:
    ips = lan_ips()
    return ips[0] if ips else "127.0.0.1"


def tailscale_ip() -> str:
    now = time.time()
    if _addr_cache["ts"] and now - _addr_cache["at"] < _ADDR_TTL * 8:
        return _addr_cache["ts"]
    exe = shutil.which("tailscale") or next(
        (p for p in (r"C:\Program Files\Tailscale\tailscale.exe",
                     r"C:\Program Files (x86)\Tailscale\tailscale.exe") if os.path.exists(p)),
        None)
    if not exe:
        return ""
    try:
        out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True,
                             timeout=6, creationflags=_no_window()).stdout
        for line in out.splitlines():
            line = line.strip()
            if line and not line.startswith("127."):
                _addr_cache["ts"] = line
                return line
    except Exception:                                             # noqa: BLE001
        pass
    return ""


def _no_window() -> int:
    return 0x08000000 if os.name == "nt" else 0


# ---------------------------------------------------------------------------
# cloudflared quick tunnel
# ---------------------------------------------------------------------------
def cloudflared_path() -> str:
    found = shutil.which("cloudflared")
    if found:
        return found
    for p in (TOOLS_DIR / "cloudflared" / "cloudflared.exe",
              TOOLS_DIR / "cloudflared.exe",
              Path(r"S:\tools\cloudflared\cloudflared.exe"),
              Path(r"S:\tools\cloudflared.exe")):
        if p.exists():
            return str(p)
    return ""


def download_cloudflared(progress=None) -> str:
    """Fetch the official cloudflared.exe into tools/. Returns its path."""
    dest = TOOLS_DIR / "cloudflared" / "cloudflared.exe"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    req = urllib.request.Request(_CF_URL, headers={"User-Agent": "Anya-UI"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as fh:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = r.read(262144)
            if not chunk:
                break
            fh.write(chunk)
            got += len(chunk)
            if progress:
                progress(got, total)
    tmp.replace(dest)
    return str(dest)


def tunnel_status() -> dict:
    with _lock:
        proc = _tunnel["proc"]
        alive = bool(proc and proc.poll() is None)
        return {"running": alive, "url": _tunnel["url"] if alive else "",
                "error": _tunnel["error"], "started": _tunnel["started"],
                "installed": bool(cloudflared_path())}


def start_tunnel(port: int) -> dict:
    """Raise a Cloudflare quick tunnel to the local UI. Idempotent."""
    with _lock:
        proc = _tunnel["proc"]
        if proc and proc.poll() is None and _tunnel["url"]:
            return {"running": True, "url": _tunnel["url"]}
        exe = cloudflared_path()
        if not exe:
            return {"running": False, "error": "cloudflared isn't installed yet"}
        _tunnel.update({"url": "", "error": "", "log": []})
        cmd = [exe, "tunnel", "--url", f"http://127.0.0.1:{port}",
               "--no-autoupdate", "--loglevel", "info"]
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=_no_window())
        except Exception as exc:                                  # noqa: BLE001
            _tunnel["error"] = str(exc)
            return {"running": False, "error": str(exc)}
        _tunnel["proc"] = proc
        _tunnel["started"] = time.time()
        threading.Thread(target=_pump, args=(proc,), daemon=True).start()

    # wait (briefly) for the public URL to appear
    for _ in range(60):
        time.sleep(0.5)
        with _lock:
            if _tunnel["url"]:
                return {"running": True, "url": _tunnel["url"]}
            if _tunnel["proc"] and _tunnel["proc"].poll() is not None:
                return {"running": False, "error": _tunnel["error"] or "tunnel exited"}
    return {"running": True, "url": "", "error": "tunnel is starting…"}


def _pump(proc: subprocess.Popen) -> None:
    try:
        for line in proc.stdout:                                  # type: ignore[union-attr]
            line = line.rstrip()
            with _lock:
                _tunnel["log"] = (_tunnel["log"] + [line])[-40:]
                if not _tunnel["url"]:
                    m = _CF_RX.search(line)
                    if m:
                        _tunnel["url"] = m.group(0)
                if "error" in line.lower() and not _tunnel["error"]:
                    _tunnel["error"] = line
    except Exception:                                             # noqa: BLE001
        pass
    finally:
        with _lock:
            if _tunnel["proc"] is proc and proc.poll() is not None:
                if not _tunnel["error"]:
                    _tunnel["error"] = "tunnel stopped"
                _tunnel["url"] = ""


def stop_tunnel() -> dict:
    with _lock:
        proc = _tunnel["proc"]
        _tunnel.update({"proc": None, "url": "", "error": "", "started": 0.0})
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:                                         # noqa: BLE001
            pass
    return {"running": False, "url": ""}
