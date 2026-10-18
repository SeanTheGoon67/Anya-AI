#!/usr/bin/env python
"""
build_cocoon_dataset.py — build fine-tuning examples from a Cocoon-style
platform config repo (e.g. inssekt/CocoonFE).

The repo is 117 platform JSON files + a couple of Python scripts. We turn each
platform into several grounded instruction/response pairs so the model learns
the *exact* schema, key order, and conventions.

Emits LLaMA-Factory "alpaca" JSONL: {instruction, input, output}

Usage:
    python build_cocoon_dataset.py --repo S:\\repos\\CocoonFE-main --out dataset\\cocoon.jsonl
"""

from __future__ import annotations

import argparse
import ast
import glob
import hashlib
import json
import os
import re
import sys

PLATFORM_KEY_ORDER = [
    "name", "uniqueId", "shortname", "description", "acceptedFilenameRegex",
    "scraperSourceList", "boxArtAspectRatioId", "useCustomBoxArtAspectRatio",
    "customBoxArtAspectRatio", "screenAspectRatioId",
    "useCustomScreenAspectRatio", "customScreenAspectRatio",
    "retroAchievementsConsoleIdList", "extra",
]
PLAYER_KEY_ORDER = [
    "name", "uniqueId", "description", "acceptedFilenameRegex",
    "amStartArguments", "killPackageProcesses", "killPackageProcessesWarning",
    "extra",
]
ROOT_KEY_ORDER = ["databaseVersion", "revisionNumber", "platform", "playerList"]


def jdump(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


def extensions_from(player: dict) -> str:
    desc = player.get("description") or ""
    m = re.search(r"extensions?:\s*([a-z0-9 ,]+)", desc, re.I)
    if m:
        return m.group(1).strip().rstrip(".")
    rx = player.get("acceptedFilenameRegex") or ""
    m = re.search(r"\\\.\(\?:([a-z0-9|]+)\)", rx, re.I)
    if m:
        return m.group(1).replace("|", ", ")
    return ""


def package_from(player: dict) -> str:
    args = player.get("amStartArguments") or ""
    m = re.search(r"-n\s+([A-Za-z0-9_.]+)/", args)
    if m:
        return m.group(1)
    uid = player.get("uniqueId") or ""
    return uid


def build(repo: str, max_examples: int):
    out, seen = [], set()

    def add(instruction, inp, outp):
        if not outp:
            return
        key = hashlib.sha1((instruction + inp).encode("utf-8", "ignore")).hexdigest()
        if key in seen:
            return
        seen.add(key)
        out.append({"instruction": instruction, "input": inp, "output": outp})

    # ---- global schema knowledge ----
    add(
        "What is the canonical key order for the top level of a Cocoon platform "
        "config file? Return them in order.",
        "",
        jdump(ROOT_KEY_ORDER),
    )
    add(
        "List the canonical key order for a Cocoon `platform` entity object.",
        "",
        jdump(PLATFORM_KEY_ORDER),
    )
    add(
        "List the canonical key order for a Cocoon `playerList` (emulator) entry.",
        "",
        jdump(PLAYER_KEY_ORDER),
    )
    add(
        "Write a minimal Cocoon platform config skeleton for a new platform, "
        "including the root keys and an empty player list.",
        "",
        jdump(
            {
                "databaseVersion": 14,
                "revisionNumber": 0,
                "platform": {k: None for k in PLATFORM_KEY_ORDER},
                "playerList": [],
            }
        ),
    )

    files = sorted(glob.glob(os.path.join(repo, "**", "*.json"), recursive=True))
    n_platforms = 0
    for path in files:
        name = os.path.basename(path)
        if name == "index.json":
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        plat = data.get("platform")
        if not isinstance(plat, dict):
            continue
        n_platforms += 1
        pname = plat.get("name") or name
        short = plat.get("shortname") or ""

        # P1: full platform entity
        add(
            f"Write the `platform` entity object for the Cocoon platform "
            f'"{pname}" (shortname "{short}"). Use the correct keys and order.',
            "",
            jdump(plat),
        )

        # P2: platform metadata summary
        add(
            f"Create the Cocoon platform metadata for {pname}: name, uniqueId, "
            "shortname, filename regex, and RetroAchievements console IDs.",
            "",
            jdump({k: plat.get(k) for k in (
                "name", "uniqueId", "shortname", "acceptedFilenameRegex",
                "retroAchievementsConsoleIdList")}),
        )

        # P3: scrapers
        scrapers = plat.get("scraperSourceList") or []
        if scrapers:
            add(
                f"List the scraper sources configured for the {pname} platform.",
                "",
                jdump(scrapers),
            )

        # P4: one example per emulator/player entry
        for player in data.get("playerList") or []:
            if not isinstance(player, dict):
                continue
            pl_name = player.get("name") or "the emulator"
            exts = extensions_from(player)
            pkg = package_from(player)
            hint = f"It launches via `{pkg}`." if pkg else ""
            add(
                f'Add a Cocoon emulator entry for "{pl_name}" to the {pname} '
                f"platform config. It accepts these file extensions: {exts}. {hint}",
                "",
                jdump(player),
            )

    # ---- code examples from the repo's Python scripts ----
    for py in sorted(glob.glob(os.path.join(repo, "**", "*.py"), recursive=True)):
        try:
            with open(py, encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        lines = text.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            start, end = node.lineno - 1, getattr(node, "end_lineno", node.lineno)
            body = "\n".join(lines[start:end])
            doc = ast.get_docstring(node) or ""
            add(
                f"Implement the Python {'class' if isinstance(node, ast.ClassDef) else 'function'} "
                f"`{node.name}` used by the Cocoon platform tooling.",
                f"# file: {os.path.basename(py)}",
                f"```python\n{body}\n```",
            )
            if doc:
                add(
                    f"Document the Python function `{node.name}` from the Cocoon tooling.",
                    doc,
                    f"```python\n{body}\n```",
                )

        if out and len(out) >= max_examples:
            break

    return out[:max_examples], n_platforms


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-examples", type=int, default=5000)
    args = ap.parse_args()

    rows, n = build(args.repo, args.max_examples)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[+] {n} platform files -> {len(rows)} examples -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
