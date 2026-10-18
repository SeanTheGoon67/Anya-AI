#!/usr/bin/env python
"""
build_chat_dataset.py — add natural conversational ability.

Pulls Databricks Dolly 15k (Apache-2.0), which is ordinary human chat/Q&A
(open Q&A, general Q&A, brainstorming, creative writing, classification,
summarisation, ...). Balancing by category stops any one kind from dominating.

This is what turns Anya from "code only" into "chatbot that also codes".

Usage:
    python build_chat_dataset.py --out dataset\\chat.jsonl --total 2500
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import defaultdict

random.seed(7)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=r"dataset\chat.jsonl")
    ap.add_argument("--total", type=int, default=2500)
    ap.add_argument("--max-output-chars", type=int, default=1200)
    ap.add_argument("--max-input-chars", type=int, default=600)
    args = ap.parse_args()

    try:
        from datasets import load_dataset
    except ImportError:
        print("pip install datasets", file=sys.stderr)
        sys.exit(1)

    print("[i] loading databricks/databricks-dolly-15k ...", file=sys.stderr)
    ds = load_dataset("databricks/databricks-dolly-15k", split="train")

    by_cat = defaultdict(list)
    for row in ds:
        cat = row.get("category") or "other"
        resp = (row.get("response") or "").strip()
        ctx = (row.get("context") or "").strip()
        instr = (row.get("instruction") or "").strip()
        if not instr or not resp:
            continue
        if len(resp) > args.max_output_chars:
            continue
        if len(ctx) > args.max_input_chars:
            continue
        by_cat[cat].append(
            {"instruction": instr, "input": ctx, "output": resp}
        )

    cats = sorted(by_cat)
    per_cat = max(1, args.total // max(1, len(cats)))
    out = []
    for c in cats:
        random.shuffle(by_cat[c])
        out.extend(by_cat[c][:per_cat])
        print(f"  {c:24} {len(by_cat[c]):6} available -> taking {min(per_cat, len(by_cat[c]))}", file=sys.stderr)

    # top up to the requested total if some categories were short
    if len(out) < args.total:
        pool = [r for c in cats for r in by_cat[c][per_cat:]]
        random.shuffle(pool)
        out.extend(pool[: args.total - len(out)])

    random.shuffle(out)
    out = out[: args.total]

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[+] {len(out)} conversational examples -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
