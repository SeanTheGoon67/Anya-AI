#!/usr/bin/env python
"""
combine.py — merge all per-source JSONL datasets into one de-duplicated set.

Usage:
    python combine.py --out dataset\\all.jsonl public.jsonl cocoon.jsonl ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dir", default="dataset")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args()

    seen, rows = set(), []
    for name in args.files:
        path = name if os.path.isabs(name) else os.path.join(args.dir, name)
        n = 0
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                o = json.loads(line)
                key = hashlib.sha1(
                    (o.get("instruction", "") + o.get("input", "")).encode("utf-8", "ignore")
                ).hexdigest()
                if key in seen:
                    continue
                seen.add(key)
                rows.append(o)
                n += 1
        print(f"  {name:26} +{n}", file=sys.stderr)

    with open(args.out, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[+] TOTAL {len(rows)} -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
