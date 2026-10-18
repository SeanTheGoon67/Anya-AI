#!/usr/bin/env python
"""
test_anya.py — a repeatable behaviour test for Anya.

Asks a fixed battery of questions covering conversation, explanations and code,
prints each answer, and writes a report to logs\\anya_test.txt with speed.

Usage:
    python tools\\test_anya.py                      # against Ollama  (ollama run anya)
    python tools\\test_anya.py --port 8090 --openai # against llama-server
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

SYSTEM = (
    "You are Anya, a friendly assistant that runs entirely on the user's own PC. "
    "Your name is Anya.\n\n"
    "You are a normal chatbot AND a coding helper:\n"
    "- If the user is just chatting, answer in natural, warm, conversational prose. "
    "Do not dump code.\n"
    "- If the user asks for code, or code is clearly the right answer, write it in a "
    "fenced code block with the language tag, with a short explanation around it.\n"
    "- Keep replies concise and readable. Match the user's tone.\n"
    "- Only output raw code with no explanation when the user explicitly asks for "
    "code only.\n\n"
    "You are especially good at Python and Kotlin / Jetpack Compose (Android), "
    "emulator-frontend configuration (platform JSON) and Cocoon Shell theme.json "
    "files.\n\n"
    "You run fully offline: you have no internet access and you never claim to. If "
    "you don't know something, say so instead of inventing it."
)

# (kind, question) — kind is only used for readability in the report
TESTS = [
    ("chat",    "What have you learned about coding?"),
    ("chat",    "What is your name, and what are you?"),
    ("chat",    "hey, how's it going?"),
    ("chat",    "I'm having a rough day. Say something nice."),
    ("chat",    "Tell me a short joke about programmers."),
    ("chat",    "What's the weather like today?"),
    ("explain", "Can you explain how Kotlin coroutines work?"),
    ("explain", "What's the difference between remember and rememberSaveable in Compose?"),
    ("explain", "Explain state hoisting in Jetpack Compose."),
    ("explain", "What is a sealed class and when should I use one?"),
    ("explain", "I'm new to Android. Where should I start learning?"),
    ("explain", "What does theme.json do in an emulator front-end like Cocoon?"),
    ("code",    "Write a Kotlin data class for a game with a title and a platform."),
    ("code",    "Write a Python function that reads a JSON file and returns a dict."),
    ("code",    "Write a Compose screen showing a scrollable list of games."),
    ("code",    "How do I launch an emulator from an Android app using an Intent?"),
    ("code",    "Show me a Retrofit interface with a suspend function."),
]


def chat_ollama(base, model, question, timeout):
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
        ],
        "stream": False,
        "options": {"temperature": 0.6, "num_ctx": 4096},
    }).encode()
    req = urllib.request.Request(
        f"{base}/api/chat", data=body,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    dt = time.time() - t0
    text = data.get("message", {}).get("content", "")
    ec = data.get("eval_count", 0) or 0
    ed = data.get("eval_duration", 0) or 1
    return text, dt, (ec / (ed / 1e9)) if ec else 0.0, ec


def chat_openai(base, model, question, timeout):
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
        ],
        "temperature": 0.6,
        "max_tokens": 512,
    }).encode()
    req = urllib.request.Request(
        f"{base}/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    dt = time.time() - t0
    ch = data["choices"][0]
    text = ch["message"]["content"]
    tc = data.get("usage", {}).get("completion_tokens", 0) or 0
    return text, dt, (tc / dt) if dt else 0.0, tc


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:11434")
    ap.add_argument("--model", default="anya")
    ap.add_argument("--port", type=int, default=None,
                    help="use this port (sets --base to http://127.0.0.1:PORT)")
    ap.add_argument("--openai", action="store_true",
                    help="use the OpenAI-compatible endpoint (llama-server)")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--out", default=r"logs\anya_test.txt")
    args = ap.parse_args()

    if args.port:
        args.base = f"http://127.0.0.1:{args.port}"
    if args.openai:
        args.base += ""

    lines, tok_total, t_total = [], 0, 0.0
    for i, (kind, question) in enumerate(TESTS, 1):
        try:
            if args.openai:
                text, dt, tps, tc = chat_openai(args.base, args.model, question, args.timeout)
            else:
                text, dt, tps, tc = chat_ollama(args.base, args.model, question, args.timeout)
        except Exception as exc:  # noqa: BLE001
            text, dt, tps, tc = f"<<ERROR: {exc}>>", 0.0, 0.0, 0
        tok_total += tc
        t_total += dt

        block = [
            "=" * 78,
            f"[{i:02d}] ({kind}) {question}",
            "-" * 78,
            text.strip(),
            f"--- {tc} tokens in {dt:.1f}s ({tps:.1f} tok/s)",
        ]
        chunk = "\n".join(block)
        print(chunk)
        lines.append(chunk)

    summary = (
        f"\n{'=' * 78}\n"
        f"SUMMARY: {len(TESTS)} tests, {tok_total} tokens in {t_total:.1f}s "
        f"({tok_total / t_total:.1f} tok/s average)\n"
    )
    print(summary)
    lines.append(summary)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"[+] report -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
