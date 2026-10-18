#!/usr/bin/env python
"""
build_kotlin_dataset.py — Android / Kotlin / Jetpack Compose instruction dataset.

Turns open-source Android (Kotlin) repos into LLaMA-Factory "alpaca" JSONL:
    {"instruction": ..., "input": ..., "output": ...}

For every top-level declaration (fun / class / object / interface) it emits real,
verifiable pairs — no LLM-generated text:

  * code -> doc  : "Write KDoc for this function"   (the real KDoc is the answer)
  * spec -> code : "Implement this function"        (the real body is the answer)

@Composable functions get Compose-specific phrasing.

Usage:
    python build_kotlin_dataset.py --repo S:\\repos\\cannoli-main --out dataset\\android_cannoli.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

SKIP_DIRS = {
    ".git", ".gradle", ".idea", ".kotlin", "build", "node_modules", "captures",
    "out", "dist", ".gitattributes",
}

FUN_RE = re.compile(r"\bfun\s+(?:<[^>{}\n]*>\s*)?([A-Za-z_][\w.]*)\s*\(")
TYPE_RE = re.compile(r"\b(?:class|interface|object)\s+([A-Za-z_]\w*)\b")
KDOC_PLAIN = re.compile(r"[ \t]*\*?[ \t]?")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def iter_source(repo: str, max_kb: int):
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if not name.endswith(".kt"):
                continue
            path = os.path.join(root, name)
            try:
                if os.path.getsize(path) > max_kb * 1024:
                    continue
            except OSError:
                continue
            yield path


def read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except OSError:
        return ""


def match_brace(text: str, open_idx: int) -> int:
    """Index just after the '}' matching the '{' at open_idx. Skips strings/comments."""
    if open_idx >= len(text) or text[open_idx] != "{":
        return -1
    depth, i, n = 0, open_idx, len(text)
    while i < n:
        c = text[i]
        if c == "{":
            depth += 1
            i += 1
        elif c == "}":
            depth -= 1
            i += 1
            if depth == 0:
                return i
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif text.startswith('"""', i):
            j = text.find('"""', i + 3)
            i = n if j < 0 else j + 3
        elif c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
            i += 1
        elif c == "'":
            i += 1
            while i < n and text[i] != "'":
                i += 2 if text[i] == "\\" else 1
            i += 1
        else:
            i += 1
    return -1


def find_open_brace(text: str, start: int) -> int:
    """First '{' at/after start that is not inside a string/comment."""
    i, n = start, len(text)
    while i < n:
        c = text[i]
        if c == "{":
            return i
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
            i += 1
        elif c == "'":
            i += 1
            while i < n and text[i] != "'":
                i += 2 if text[i] == "\\" else 1
            i += 1
        elif c == "\n":
            return -1  # expression-body / abstract decl — no block
        i += 1
    return -1


def preceding_meta(text: str, idx: int):
    """Return (annotations, kdoc) immediately preceding idx, else ('', '')."""
    head = text[:idx]
    kdoc, annos = "", ""
    # annotations sit between KDoc and the declaration
    m = re.search(r"([ \t]*(?:@[\w.]+(?:\s*\([^()]*\))?[ \t]*\r?\n?)+)[ \t]*$", head)
    if m:
        annos = m.group(1)
        head = head[: m.start()]
    j = head.rfind("*/")
    if j != -1:
        k = head.rfind("/**", 0, j)
        if k != -1 and head[j + 2:].strip() == "":
            kdoc = head[k:j + 2]
    return annos.strip(), kdoc


def kdoc_to_text(kdoc: str) -> str:
    body = kdoc.strip()
    if body.startswith("/**"):
        body = body[3:]
    if body.endswith("*/"):
        body = body[:-2]
    lines = []
    for ln in body.splitlines():
        ln = re.sub(r"^\s*\*?\s?", "", ln).strip()
        if ln.startswith("@"):  # keep tags inline
            ln = ln[1:]
        if ln:
            lines.append(ln)
    return " ".join(lines).strip()


def one_line(s: str, limit: int) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "\u2026"


# --------------------------------------------------------------------------- #
# generation
# --------------------------------------------------------------------------- #
def declarations(text: str):
    """Yield (kind, name, sig, body, kdoc, annos) for plausible declarations."""
    seen = set()
    for regex, kind in ((FUN_RE, "function"), (TYPE_RE, "type")):
        for m in regex.finditer(text):
            idx = m.start()
            if idx in seen:
                continue
            brace = find_open_brace(text, m.end())
            if brace == -1:
                continue
            end = match_brace(text, brace)
            if end == -1:
                continue
            sig = text[idx:brace].strip()
            body = text[idx:end].strip()
            if not (20 < len(sig) < 400) or not (80 < len(body) < 2200):
                continue
            name = m.group(1).split(".")[-1]
            annos, kdoc = preceding_meta(text, idx)
            if kind == "type" and ("class " in sig[:80] or "object " in sig[:80] or "interface " in sig[:80]):
                pass
            seen.add(idx)
            yield kind, name, sig, body, kdoc, annos


def build(repo: str, max_kb: int, max_examples: int, per_file: int):
    out, seen = [], set()

    def add(instruction, inp, output):
        if not instruction or not output:
            return
        key = hashlib.sha1((instruction + inp).encode("utf-8", "ignore")).hexdigest()
        if key in seen:
            return
        seen.add(key)
        out.append({"instruction": instruction, "input": inp, "output": output})

    files = sorted(iter_source(repo, max_kb))
    print(f"[i] {len(files)} Kotlin files under {repo}", file=sys.stderr)

    for path in files:
        text = read(path)
        if len(text) < 200:
            continue
        n_file = 0
        for kind, name, sig, body, kdoc, annos in declarations(text):
            doc = kdoc_to_text(kdoc)
            is_compose = "@Composable" in annos
            label = "composable" if is_compose else kind
            code = f"```kotlin\n{body}\n```"

            # 1) code -> documentation  (real KDoc)
            if len(doc) > 40:
                add(
                    f"Write KDoc documentation comments for the Kotlin {label} "
                    f"shown below (Android app). Describe what it does, its "
                    f"parameters and return value.",
                    f"```kotlin\n{sig}\n```",
                    kdoc.strip(),
                )

            # 2) spec -> code  (real body)
            if is_compose:
                lead = (
                    f"Write a Jetpack Compose @Composable `{name}` for an Android app."
                    + (f"\n\nRequirement: {one_line(doc, 400)}" if doc else "")
                )
            elif doc:
                lead = (
                    f"Android app (Kotlin). Implement the {kind} `{name}` to match "
                    f"this description:\n\n{one_line(doc, 400)}"
                )
            else:
                lead = (
                    f"Implement this Kotlin {kind} (`{name}`) for an Android app. "
                    f"Return only the code."
                )
            add(lead, f"```kotlin\n{sig}\n```", code)

            n_file += 1
            if n_file >= per_file or len(out) >= max_examples:
                break
        if len(out) >= max_examples:
            break

    return out[:max_examples]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-examples", type=int, default=4000)
    ap.add_argument("--max-file-kb", type=int, default=120)
    ap.add_argument("--per-file", type=int, default=40)
    args = ap.parse_args()

    rows = build(args.repo, args.max_file_kb, args.max_examples, args.per_file)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[+] {len(rows)} examples -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
