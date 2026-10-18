#!/usr/bin/env python
"""
build_dataset.py — turn a code repository into a fine-tuning dataset.

Produces LLaMA-Factory "alpaca" format JSONL:
    {"instruction": ..., "input": ..., "output": ...}

Task types generated per file:
  1. explain   — describe what the file/code does
  2. docstring — write documentation for a function/class
  3. complete  — given a signature + docstring, produce the body (code-completion style)

Usage:
    python build_dataset.py --repo C:\\path\\to\\repo --out dataset\\mine.jsonl
    python build_dataset.py --public --out dataset\\public.jsonl

Notes:
  - Only text/code files under --max-file-kb are read.
  - Results are de-duplicated and capped by --max-examples.
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

CODE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".kts", ".c", ".h",
    ".cpp", ".hpp", ".cc", ".cs", ".go", ".rs", ".rb", ".php", ".swift",
    ".lua", ".sql", ".sh", ".ps1", ".psm1", ".html", ".css", ".scss",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".md", ".xml",
}

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "vendor", "dist", "build", "out",
    "bin", "obj", ".venv", "venv", "env", "__pycache__", ".idea", ".vscode",
    "target", "coverage", ".next", ".nuxt", "Pods",
}


def iter_files(repo: str, max_file_kb: int):
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".git")]
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext not in CODE_EXTS:
                continue
            path = os.path.join(root, name)
            try:
                if os.path.getsize(path) > max_file_kb * 1024:
                    continue
            except OSError:
                continue
            yield path


def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except OSError:
        return ""


def rel(repo: str, path: str) -> str:
    return os.path.relpath(path, repo).replace("\\", "/")


def gen_explain(repo: str, path: str, text: str):
    lines = text.splitlines()
    if len(lines) < 5:
        return
    body = "\n".join(lines[:80])[:2500]
    yield {
        "instruction": (
            "Explain what this file does. Cover its purpose, the main "
            "functions/classes, and how the pieces fit together."
        ),
        "input": f"File: {rel(repo, path)}\n\n```\n{body}\n```",
        "output": (
            f"This file `{rel(repo, path)}` contains {len(lines)} lines of code. "
            "It defines the logic shown below. (Replace this placeholder with a "
            "real explanation — see build_dataset.py --enrich.)"
        ),
    }


def gen_python_members(repo: str, path: str, text: str):
    """Pull real functions/classes out of Python files via AST."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return
    src_lines = text.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        doc = ast.get_docstring(node) or ""
        sig = src_lines[node.lineno - 1].strip()
        start, end = node.lineno - 1, getattr(node, "end_lineno", node.lineno)
        body = "\n".join(src_lines[start:end])[:2000]
        kind = "class" if isinstance(node, ast.ClassDef) else "function"

        yield {
            "instruction": (
                f"Write a clear docstring for this Python {kind} named "
                f"`{node.name}`. Describe its purpose, parameters, return value, "
                "and any side effects."
            ),
            "input": f"```python\n{body}\n```",
            "output": doc or f'"""Docstring for {node.name}."""',
        }

        if len(sig) > 5 and end - start >= 2:
            yield {
                "instruction": (
                    "Implement this Python function. Return only the function body."
                ),
                "input": f"```python\n{sig}\n    # ...\n```",
                "output": f"```python\n{body}\n```",
            }


def gen_comments(repo: str, path: str, text: str):
    """Use leading comments as natural-language instructions."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("#") or s.startswith("//"):
            comment = re.sub(r"^(#+|//+)\s*", "", s).strip()
            if len(comment) < 20:
                continue
            nxt = "\n".join(lines[i + 1:i + 12]).strip()
            if len(nxt) < 15:
                continue
            yield {
                "instruction": comment,
                "input": "",
                "output": f"```\n{nxt[:800]}\n```",
            }
            break  # one per file is enough


def build(repo: str, max_file_kb: int, max_examples: int, enrich: bool):
    seen = set()
    out = []

    def add(ex):
        if not ex:
            return
        key = hashlib.sha1(
            (ex["instruction"] + ex["input"]).encode("utf-8", "ignore")
        ).hexdigest()
        if key in seen:
            return
        seen.add(key)
        out.append(ex)

    files = list(iter_files(repo, max_file_kb))
    print(f"[i] scanning {len(files)} files under {repo}", file=sys.stderr)

    for path in files:
        text = read_text(path)
        if len(text) < 120:
            continue
        for ex in gen_explain(repo, path, text):
            if enrich:
                add(ex)
        if path.lower().endswith(".py"):
            for ex in gen_python_members(repo, path, text):
                add(ex)
        for ex in gen_comments(repo, path, text):
            add(ex)
        if len(out) >= max_examples:
            break

    return out[:max_examples]


def build_public(max_examples: int):
    """Fetch a small public coding dataset to learn the training pipeline."""
    try:
        from datasets import load_dataset
    except ImportError:
        print("pip install datasets", file=sys.stderr)
        sys.exit(1)

    ds = load_dataset(
        "iamtarun/python_code_instructions_18k_alpaca", split="train"
    )
    out = []
    for row in ds.select(range(min(max_examples, len(ds)))):
        out.append(
            {
                "instruction": row["instruction"],
                "input": row.get("input", "") or "",
                "output": row["output"],
            }
        )
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", help="path to a code repository")
    ap.add_argument("--out", required=True, help="output JSONL path")
    ap.add_argument("--public", action="store_true",
                    help="use a public coding dataset instead of a repo")
    ap.add_argument("--max-examples", type=int, default=2000)
    ap.add_argument("--max-file-kb", type=int, default=200)
    ap.add_argument("--enrich", action="store_true",
                    help="include 'explain' examples (need real answers, off by default)")
    args = ap.parse_args()

    if args.public:
        rows = build_public(args.max_examples)
    elif args.repo:
        rows = build(args.repo, args.max_file_kb, args.max_examples, args.enrich)
    else:
        ap.error("pass --repo PATH or --public")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[+] wrote {len(rows)} examples -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
