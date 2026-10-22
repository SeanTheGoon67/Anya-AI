#!/usr/bin/env python
"""
memory.py — Anya's long-term memory of you.

A tiny, stdlib-only store of durable facts ("lives in Norway", "prefers Kotlin",
"working on a Coin Flip app"). They live in one JSON file on disk, they are
injected into her system prompt so she actually uses them, and you can read,
delete or wipe them from the Memory tab.

Facts come in two ways:
  * learned automatically after an exchange — a couple of high-precision
    patterns catch the obvious ones ("my name is …", "I prefer …"), and the
    model itself is asked for anything else it notices, in a strict JSON shape
    that is validated before anything is written.
  * typed in by hand on the Memory tab.

The module never decides anything on its own: it only stores text. Keeping the
"should she remember this?" judgement in one small, inspectable place is
deliberate — a 1.5B model asked to remember things will happily remember
nonsense, so everything here is conservative and easy to delete.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path

DEFAULT_DIR = Path(r"S:\anya-memory")
MAX_FACTS = 400                 # oldest are dropped past this
MAX_FACT_LEN = 200

_root = DEFAULT_DIR
_lock = threading.RLock()


class MemoryError(RuntimeError):
    pass


def configure(root=None) -> None:
    global _root
    if root:
        _root = Path(root)


def root() -> Path:
    return _root


def path() -> Path:
    return _root / "memory.json"


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------

def _read() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:                                             # noqa: BLE001
        pass
    return {"facts": []}


def _write(obj: dict) -> None:
    _root.mkdir(parents=True, exist_ok=True)
    path().write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def load() -> list:
    """Every stored fact, oldest first."""
    return list(_read().get("facts") or [])


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(s).lower()).strip()


def clean_fact(text: str) -> str:
    """Normalise one candidate fact, or return "" if it isn't worth storing."""
    t = " ".join(str(text or "").split()).strip().strip("-•*\"'` ")
    if len(t) < 4 or len(t) > MAX_FACT_LEN:
        return ""
    if t.endswith("?"):
        return ""
    low = t.lower()
    for bad in ("i can't", "i cannot", "as an ai", "i'm sorry", "i don't know",
                "unknown", "unclear", "n/a", "no information", "nothing to",
                "user's name is user", "not sure"):
        if bad in low:
            return ""
    # she must not remember her own promises or code dumps as facts
    if t.startswith("```") or "\n" in t:
        return ""
    # transient or technical claims are not durable memories about a person:
    # "Latest version is 3.15.0" came from a web search, "my latest version of
    # Python was 3.15.0" was her own paraphrase. Neither should be remembered.
    if re.search(r"(?i)\b(version|release[sd]?|update[sd]?|changelog|"
                 r"latest|newest|current version|as of|deprecat)\b", t) \
            and re.search(r"\d", t):
        return ""
    if re.search(r"\bv?\d+\.\d+(\.\d+)?\b", t):
        return ""
    return t


def add(texts, source: str = "chat") -> list:
    """Add facts, skipping duplicates. Returns the ones actually stored."""
    if isinstance(texts, str):
        texts = [texts]
    cleaned = [clean_fact(t) for t in (texts or [])]
    cleaned = [t for t in cleaned if t]
    if not cleaned:
        return []
    with _lock:
        obj = _read()
        facts = obj.setdefault("facts", [])
        have = {_norm(f.get("text", "")) for f in facts}
        added = []
        for t in cleaned:
            n = _norm(t)
            if not n or n in have:
                continue
            # treat one fact containing another as the same memory
            if any((len(n) > 10 and len(h) > 10 and (n in h or h in n)) for h in have):
                continue
            # near-duplicates too: the heuristics and the model often phrase the
            # same thing twice ("is working on a weather app" / "works on a
            # weather app"), so compare the distinctive words they share.
            cand = _distinctive(t)
            if cand and _overlaps(cand, facts):
                continue
            fact = {"id": uuid.uuid4().hex[:10], "text": t,
                    "added": int(time.time()), "source": source}
            facts.append(fact)
            have.add(n)
            added.append(fact)
        if len(facts) > MAX_FACTS:
            obj["facts"] = facts[-MAX_FACTS:]
        _write(obj)
        return added


def remove(fid: str) -> bool:
    with _lock:
        obj = _read()
        facts = obj.get("facts") or []
        keep = [f for f in facts if f.get("id") != fid]
        if len(keep) == len(facts):
            return False
        obj["facts"] = keep
        _write(obj)
        return True


def clear() -> int:
    with _lock:
        obj = _read()
        n = len(obj.get("facts") or [])
        obj["facts"] = []
        _write(obj)
        return n


# ---------------------------------------------------------------------------
# recall — pick the facts worth injecting for this message
# ---------------------------------------------------------------------------

_STOP = set("a an the and or but of to in on for with at by is are was were be been "
            "i you he she it we they me my your his her its our their this that these "
            "those do does did can could would should will shall may might must not no "
            "yes if then than as so about into over after before from up down out".split())

# Words that carry no memory value on their own: "User likes X" should be
# verified against X, not against the word "likes".
_MEM_VERBS = set("user users name names likes like loves love prefers prefer "
                 "uses use using lives live living working works work building "
                 "build builds built based called call going wants want thinks "
                 "think really also just very am is are was were".split())


def _words(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", str(s).lower())
            if len(w) > 2 and w not in _STOP}


def _distinctive(text: str) -> set:
    """Content words of a candidate fact — the ones that must be justified."""
    return {w for w in re.findall(r"[a-z0-9]+", str(text).lower())
            if len(w) >= 2 and w not in _MEM_VERBS and w not in _STOP}


def _overlaps(cand: set, facts: list) -> bool:
    """True when a candidate fact's content words mostly match an existing one."""
    for f in facts:
        other = _distinctive(f.get("text", ""))
        if not other:
            continue
        inter = cand & other
        if len(inter) >= max(2, round(min(len(cand), len(other)) * 0.6)):
            return True
    return False


def grounded(fact: str, user_text: str) -> bool:
    """True when the fact is supported by what the *user* actually said.

    A small model happily invents plausible memories ("User's name is Anya",
    "User lives in Berlin"). Requiring the fact's distinctive words to appear in
    the user's own message throws almost all of those away.

    Two facts get extra scrutiny because they were the ones that got through:

    * A single shared word is not evidence. "User's name is Python" used to pass
      on a message about "the latest version of python", because Python reduces to
      that one content word. Anything leaner than two matching content words must
      be a *name* fact with a real introduction ("my name is X", "call me X").
    * Name facts must come from an introduction, never from a word that merely
      appears somewhere in the message.
    """
    user_text = user_text or ""
    fw, uw = _distinctive(fact), _distinctive(user_text)
    if not fw or not uw:
        return False

    low = fact.lower()
    is_name = low.startswith("user's name is") or low.startswith("user likes to be called")
    if is_name:
        # only trust it when the user actually introduced themselves
        m = re.search(r"(?i)\b(?:my name'?s|my name is|call me)\s+([A-Z][\w'’-]{1,24})",
                      user_text)
        if not m:
            return False
        return m.group(1).strip().lower() in fw

    inter = fw & uw
    if len(fw) <= 2:
        # a claim this short must be fully backed by the user's own words
        return inter == fw
    return len(inter) >= 2


def relevant(query: str = "", limit: int = 30) -> list:
    """Facts most likely to matter for this message, newest first on ties."""
    facts = load()
    if not facts:
        return []
    if not query:
        return facts[-limit:]
    if len(facts) <= limit:
        return facts
    q = _words(query)
    scored = []
    for i, f in enumerate(facts):
        fw = _words(f.get("text", ""))
        overlap = len(q & fw)
        # recency tiebreak: newer facts score a hair higher
        score = overlap * 10 + i / max(len(facts), 1)
        scored.append((score, f))
    scored.sort(key=lambda x: x[0], reverse=True)
    picked = [f for s, f in scored[:limit] if s > 0]
    return picked or facts[-limit:]


def context_block(query: str = "", limit: int = 30) -> str:
    """The text appended to the system prompt so she remembers you."""
    facts = relevant(query, limit)
    if not facts:
        return ""
    lines = "\n".join("- " + f["text"] for f in facts)
    return (
        "\n\nLong-term memory — things you have learned about this user over time. "
        "Treat them as true and use them naturally when they are relevant (don't "
        "recite the list, and don't mention that you have a memory file):\n"
        + lines + "\n"
    )


# ---------------------------------------------------------------------------
# learning — pull new facts out of a finished exchange
# ---------------------------------------------------------------------------

EXTRACT_PROMPT = (
    "You keep a long-term memory of the user. Read the exchange below and list "
    "ONLY durable facts about the USER that are worth remembering for future "
    "conversations — their name, where they live, what they like or dislike, "
    "their job, their projects, their tools, their goals. "
    "Do NOT list questions, the assistant's words, temporary details, or things "
    "that will be stale tomorrow. If there is nothing worth keeping, reply with "
    "an empty list.\n\n"
    "Reply with ONLY a JSON array of short factual sentences about the user, "
    "for example:\n"
    '["User\'s name is Sam", "User prefers Kotlin for Android", "User is building a Coin Flip app"]\n'
    "No prose, no markdown — just the array."
)

# High-precision patterns. Deliberately conservative: a wrong memory is worse
# than a missing one, and everything here is also visible/deletable in the UI.
_PATTERNS = [
    (r"\bmy name'?s\s+([A-Z][\w'’-]{1,24})", "User's name is {0}"),
    (r"\bmy name is\s+([A-Z][\w'’-]{1,24})", "User's name is {0}"),
    (r"\bcall me\s+([A-Z][\w'’-]{1,24})", "User likes to be called {0}"),
    (r"\bi(?:'m| am) (?:from|based in|living in)\s+([A-Z][\w'’-]+(?:[ ,][A-Z][\w'’-]+){0,2})",
     "User is based in {0}"),
    (r"\bi live in\s+([A-Z][\w'’-]+(?:[ ,][A-Z][\w'’-]+){0,2})", "User lives in {0}"),
    (r"\bi(?:'m| am) work(?:ing)? on\s+(?:an?\s+)?([^.,;!?\n]{3,70})",
     "User is working on {0}"),
    (r"\bi(?:'m| am) build(?:ing)?\s+(?:an?\s+)?([^.,;!?\n]{3,70})",
     "User is building {0}"),
    (r"\bi (?:really )?(?:prefer|like|love|enjoy)\s+([^.,;!?\n]{3,70})",
     "User likes {0}"),
    (r"\bi (?:really )?(?:hate|dislike|can'?t stand)\s+([^.,;!?\n]{3,70})",
     "User dislikes {0}"),
    (r"\bi (?:mainly |usually |mostly )?use\s+([^.,;!?\n]{3,70})", "User uses {0}"),
    (r"\bi work (?:as|in)\s+([^.,;!?\n]{3,70})", "User works as {0}"),
    (r"\bmy (?:favourite|favorite)\s+([a-z ]{3,30}) is\s+([^.,;!?\n]{2,50})",
     "User's favourite {0} is {1}"),
]


def extract_from_text(text: str) -> list:
    """Cheap, deterministic facts from what the *user* typed."""
    out = []
    for pat, tmpl in _PATTERNS:
        for m in re.finditer(pat, text, re.I):
            try:
                vals = [g.strip().rstrip(".,!") for g in m.groups()]
            except Exception:                                     # noqa: BLE001
                continue
            if not vals or not vals[0]:
                continue
            # first group of a name must look like a name, not a common word
            if tmpl.startswith("User's name is") and vals[0].lower() in _STOP:
                continue
            out.append(tmpl.format(*vals))
    return out


def parse_extraction(raw: str) -> list:
    """Turn the model's reply into a list of fact strings (best effort)."""
    if not raw:
        return []
    text = raw.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start, end = text.find("["), text.rfind("]")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    try:
        data = json.loads(text)
    except Exception:                                             # noqa: BLE001
        # fall back to line-by-line bullets
        return [ln.lstrip("-•* \t").strip()
                for ln in raw.splitlines() if ln.strip().startswith(("-", "•", "*"))]
    if isinstance(data, dict):
        data = data.get("facts") or data.get("memories") or []
    if not isinstance(data, list):
        return []
    return [str(x) for x in data if isinstance(x, (str, int, float))]


def learn_from_exchange(user_text: str, assistant_text: str,
                        ask_model=None) -> list:
    """Collect facts from one exchange: user patterns first, then the model.

    Everything is filtered through grounded(): a fact only survives if the
    user's own message contains its distinctive words, which is what keeps a
    small model's invented memories out of the file.
    """
    user_text = user_text or ""
    candidates = extract_from_text(user_text)
    if ask_model:
        try:
            prompt = (EXTRACT_PROMPT + "\n\n---\nUSER: "
                      + user_text.strip()[:1200]
                      + "\nASSISTANT: " + (assistant_text or "").strip()[:1200]
                      + "\n---\nJSON array of facts about the user:")
            raw = ask_model(prompt)
            candidates += parse_extraction(raw)
        except Exception:                                         # noqa: BLE001
            pass
    kept = [c for c in candidates if grounded(c, user_text)]
    return add(kept, source="chat")


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------

def _selftest() -> int:
    import tempfile
    global _root
    keep = _root
    _root = Path(tempfile.mkdtemp(prefix="anya-mem-"))
    fails = 0
    try:
        add(["User's name is Sam", "User prefers Kotlin for Android"])
        if len(load()) != 2:
            print("  FAIL add"); fails += 1
        add(["User's name is Sam"])                    # duplicate
        if len(load()) != 2:
            print("  FAIL dedupe"); fails += 1
        if not extract_from_text("Hi, my name is Robin and I love dark themes."):
            print("  FAIL patterns"); fails += 1
        if parse_extraction('Sure! ```json\n["User likes tea"]\n```') != ["User likes tea"]:
            print("  FAIL parse"); fails += 1
        if clean_fact("Is this a question?"):
            print("  FAIL question filter"); fails += 1
        # grounding: invented facts must be thrown away, real ones kept
        if not grounded("User's name is Robin", "hi my name is Robin"):
            print("  FAIL grounded keeps a real fact"); fails += 1
        for bogus in ("User's name is Anya", "User lives in Berlin",
                      "User likes Kotlin"):
            if grounded(bogus, "hi my name is Robin and I love dark themes"):
                print("  FAIL grounded let through:", bogus); fails += 1
        # a single shared content word is not evidence: this pair is how "User's
        # name is Python" got remembered from a search about Python versions
        for bogus, msg in (
            ("User's name is Python", "the latest version of python"),
            ("User likes to be called Python", "search the web for python"),
            ("User's name is Anya", "what have you learned about coding?"),
        ):
            if grounded(bogus, msg):
                print("  FAIL grounded accepted a name with no introduction:",
                      bogus); fails += 1
        # a name only counts when the user actually introduced themselves
        if not grounded("User's name is Robin", "call me Robin please"):
            print("  FAIL grounded missed 'call me X'"); fails += 1
        # transient web facts and version strings are not durable memories
        for junk in ("Latest version is 3.15.0", "Python 3.15.0 was released",
                     "The current version is 3.16"):
            if clean_fact(junk):
                print("  FAIL clean_fact kept a transient fact:", junk); fails += 1
        # phrasing variants of one fact should collapse to a single memory
        clear()
        add(["User works on a weather app for Android"])
        add(["User is working on weather app for Android"])
        if len(load()) != 1:
            print("  FAIL near-duplicate phrasing"); fails += 1
        clear()
        clear()
        add(["User's name is Sam"])
        learned = learn_from_exchange(
            "my name is Robin and I love dark themes", "",
            ask_model=lambda p: '[\"User\'s name is Anya\", \"User likes dark themes\"]')
        texts = [f["text"] for f in load()]
        if not any("Robin" in t for t in texts):
            print("  FAIL learn missed the real fact"); fails += 1
        if any("Anya" in t for t in texts):
            print("  FAIL learn stored an invented fact"); fails += 1
        if not context_block("kotlin"):
            print("  FAIL context"); fails += 1
        clear()
        if load():
            print("  FAIL clear"); fails += 1
    finally:
        _root = keep
    return fails


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
