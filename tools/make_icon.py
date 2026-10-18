#!/usr/bin/env python
"""make_icon.py - build Anya's icon (anya.ico + anya.png) from her portrait.

Reads the source image (`assets/anya-source.jpg` by default), centre-crops it to
a square, and writes, in the project root:

    anya.ico   multi-size (16/24/32/48/64/128/256) for the desktop,
               Start menu and taskbar
    anya.png   256 px - her in-app avatar and the browser-tab favicon
               (served by her app at /anya.png and /anya.ico)

Re-run it whenever you change the source image:

    S:\\envs\\ai\\Scripts\\python.exe tools\\make_icon.py
    S:\\envs\\ai\\Scripts\\python.exe tools\\make_icon.py "C:\\path\\to\\other.jpg"

Pure PIL, no dependencies beyond the venv.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "assets" / "anya-source.jpg"
OUT = ROOT / "anya.ico"
PNG = ROOT / "anya.png"
SIZES = [16, 24, 32, 48, 64, 128, 256]


def square(img: Image.Image, side: int | None = None) -> Image.Image:
    """Centre-crop to a square (icons want 1:1, a phone portrait is not)."""
    img = img.convert("RGB")
    w, h = img.size
    side = side or min(w, h)
    left = max((w - side) // 2, 0)
    top = max((h - side) // 2, 0)
    return img.crop((left, top, left + side, top + side))


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC
    if not src.exists():
        raise SystemExit(f"no source image at {src}")

    sq = square(Image.open(src))
    big = sq.resize((256, 256), Image.LANCZOS)

    # multi-size .ico for the desktop / Start menu / taskbar
    big.save(OUT, format="ICO", sizes=[(s, s) for s in SIZES])
    # 256 px png for the app avatar and the favicon
    big.save(PNG, format="PNG")

    print(f"[+] wrote {OUT.name} ({OUT.stat().st_size:,} bytes) "
          f"and {PNG.name} ({PNG.stat().st_size:,} bytes) from {src.name} "
          f"({sq.width}x{sq.height})")


if __name__ == "__main__":
    main()
