#!/usr/bin/env python
"""
build_teaching_dataset.py — Android/Kotlin *teaching* data from real repos.

Unlike build_kotlin_dataset.py (which turns source declarations into
"implement this" pairs), this builder mines the things that actually teach a
person to code:

  * Markdown docs / tutorials (README, docs/**, guides) -> explainer Q&A
  * KDoc comments on declarations -> "what does X do?" Q&A

The result is that Anya can *answer questions about coding*, not just emit code.

Usage:
    python build_teaching_dataset.py --root S:\\repos-teach --out dataset\\teaching.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys

random.seed(11)

SKIP_DIRS = {
    ".git", ".github", ".gradle", ".idea", ".kotlin", "build", "node_modules",
    "captures", "out", "dist", "gradle", ".circleci", "scripts",
}
SKIP_FILE_RE = re.compile(
    r"(changelog|license|licence|contributing|code[_-]?of[_-]?conduct|security|"
    r"acknowledge?ments?|credits|sponsors?|support|faq|release[_-]?notes|"
    r"pull_request_template|issue_template|notice|third[_-]?party)",
    re.I,
)
SKIP_HEADING_RE = re.compile(
    r"^(table of contents|contents|license|licence|changelog|contributing|"
    r"acknowledge?ments?|credits|sponsors?|code of conduct|legal|"
    r"version history|release notes|installation|how to run|build instructions|"
    r"about the (author|team)|contact|links|references|see also|footnotes?)\b",
    re.I,
)
# docs that are really project paperwork
SKIP_BODY_RE = re.compile(r"\b(apache license|mit license|gnu general public)\b", re.I)

HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
REF_LINK = re.compile(r"\[([^\]]*)\]\[[^\]]*\]")
BADGE = re.compile(r"^\s*\[!\[.*$")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except OSError:
        return ""


def clean_md(text: str) -> str:
    text = HTML_COMMENT.sub("", text)
    text = MD_IMAGE.sub("", text)
    text = REF_LINK.sub(r"\1", text)
    text = MD_LINK.sub(r"\1", text)
    lines = []
    for ln in text.splitlines():
        if BADGE.match(ln):
            continue
        lines.append(ln.rstrip())
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def topic_for(name: str) -> str:
    n = name.lower().replace("\\", "/")
    if "coroutine" in n:
        return "Kotlin coroutines"
    if "kotlin-web-site" in n or "by-example" in n or "workshop" in n:
        return "Kotlin"
    if "compose" in n or "codelab" in n:
        return "Jetpack Compose"
    if "nowinandroid" in n or "architecture" in n or "sunflower" in n:
        return "Android app architecture"
    if "roadmap" in n:
        return "Android development"
    return "Android and Kotlin"


def is_linky(body: str) -> bool:
    lines = [l for l in body.splitlines() if l.strip()]
    if not lines:
        return True
    linky = sum(1 for l in lines if l.strip().startswith(("- [", "* [", "|", "http")))
    return linky / len(lines) > 0.5


def md_sections(path: str):
    text = clean_md(read(path))
    if len(text) < 200 or SKIP_BODY_RE.search(text[:2000]):
        return
    cur_head, buf = None, []
    for ln in text.splitlines():
        m = HEADING.match(ln)
        if m:
            if cur_head:
                yield cur_head, "\n".join(buf).strip()
            cur_head, buf = m.group(2).strip(), []
        else:
            buf.append(ln)
    if cur_head:
        yield cur_head, "\n".join(buf).strip()


MD_TEMPLATES = [
    "Explain {h} when building {t} apps.",
    "What is {h} and why does it matter in {t}?",
    "Teach me about {h} ({t}).",
    "I'm learning {t}. Can you explain {h}?",
    "How does {h} work in {t}?",
    "Walk me through {h} in {t}.",
    "Summarise what a developer needs to know about {h} in {t}.",
]


def build_md(root: str, per_file: int, max_out: int):
    docs = []
    for r, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if not f.lower().endswith(".md") or SKIP_FILE_RE.search(f):
                continue
            docs.append(os.path.join(r, f))
    docs.sort()
    print(f"[i] {len(docs)} markdown files", file=sys.stderr)

    rows = []
    for path in docs:
        topic = topic_for(path)
        n = 0
        for head, body in md_sections(path):
            if not head or len(body) < 120:
                continue
            if SKIP_HEADING_RE.match(head):
                continue
            if is_linky(body):
                continue
            body = body[:1600].strip()
            tmpl = MD_TEMPLATES[hash(head + path) % len(MD_TEMPLATES)]
            rows.append({
                "instruction": tmpl.format(h=f'"{head}"', t=topic),
                "input": "",
                "output": body,
            })
            n += 1
            if n >= per_file or len(rows) >= max_out:
                break
        if len(rows) >= max_out:
            break
    return rows


# --------------------------------------------------------------------------- #
# KDoc  ->  "what does X do?"
# --------------------------------------------------------------------------- #
KDOC_BLOCK = re.compile(r"/\*\*(.*?)\*/", re.S)
DECL_AFTER = re.compile(
    r"^\s*(?:@\w+(?:\([^)]*\))?\s*)*"
    r"(?:(?:public|private|internal|protected|open|abstract|sealed|data|inline|"
    r"expect|actual|suspend|override|operator|infix|external|lateinit|const|"
    r"tailrec|vararg|noinline|crossinline)\s+)*"
    r"(fun|class|interface|object|val|var|enum class|typealias)\s+"
    r"(?:<[^>]*>\s*)?([A-Za-z_][\w]*)",
    re.M,
)

KDOC_TEMPLATES = [
    "In {t}, what does `{n}` do?",
    "Explain the Kotlin {k} `{n}` from an Android project.",
    "What is `{n}` used for in {t}?",
    "Describe `{n}` ({t}).",
]


def kdoc_text(raw: str) -> str:
    out = []
    for ln in raw.splitlines():
        ln = re.sub(r"^\s*\*?\s?", "", ln).strip()
        if ln.startswith("@"):
            ln = ln[1:]
        if ln:
            out.append(ln)
    return " ".join(out).strip()


def build_kdoc(root: str, per_file: int, max_out: int):
    rows = []
    for r, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if not f.endswith(".kt"):
                continue
            path = os.path.join(r, f)
            try:
                if os.path.getsize(path) > 200 * 1024:
                    continue
            except OSError:
                continue
            low = path.lower().replace("\\", "/")
            if "/test/" in low or "/androidtest/" in low or "/tests/" in low:
                continue
            text = read(path)
            topic = topic_for(path)
            n = 0
            for m in KDOC_BLOCK.finditer(text):
                tail = text[m.end(): m.end() + 400]
                d = DECL_AFTER.match(tail)
                if not d:
                    continue
                kind, name = d.group(1), d.group(2)
                if name.lower().startswith(("test", "assert", "check")):
                    continue
                doc = kdoc_text(m.group(1))
                if len(doc) < 70:
                    continue
                tmpl = KDOC_TEMPLATES[hash(name + path) % len(KDOC_TEMPLATES)]
                rows.append({
                    "instruction": tmpl.format(t=topic, n=name, k=kind),
                    "input": "",
                    "output": doc[:1400],
                })
                n += 1
                if n >= per_file or len(rows) >= max_out:
                    break
            if len(rows) >= max_out:
                break
    print(f"[i] kdoc examples: {len(rows)}", file=sys.stderr)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True, help="folder containing the repos")
    ap.add_argument("--out", default=r"dataset\teaching.jsonl")
    ap.add_argument("--max-md", type=int, default=4200)
    ap.add_argument("--max-kdoc", type=int, default=2600)
    ap.add_argument("--per-file", type=int, default=25)
    args = ap.parse_args()

    rows = build_md(args.root, args.per_file, args.max_md)
    rows += build_kdoc(args.root, args.per_file, args.max_kdoc)

    seen, keep = set(), []
    for r in rows:
        key = hashlib.sha1(
            (r["instruction"] + r["output"][:200]).encode("utf-8", "ignore")
        ).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        keep.append(r)

    random.shuffle(keep)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        for r in keep:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[+] {len(keep)} teaching examples -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
