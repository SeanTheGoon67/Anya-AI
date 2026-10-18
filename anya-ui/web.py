#!/usr/bin/env python
"""
web.py — Anya's web browsing, using nothing but the standard library.

It gives the app four small, boring, testable things:

    search(query)          -> [{title, url, snippet}]  (via DuckDuckGo, no API key)
    page_text(url)         -> {title, url, text}       (a page, cut down to size)
    find_urls(text)        -> links the user pasted, ready to open
    parse_tool_call(text)  -> recognises the tiny JSON block Anya emits when she
                              wants to search or open a page

Everything is bounded — bytes, seconds, characters — and limited to public
http/https hosts, so a stray link can't reach into this machine's own network.

Anya was never trained for real function-calling, so the protocol is textual and
deliberately minimal: she answers with one small JSON object, and this module
turns that into an action. See GUIDE.md for the whole picture.
"""
from __future__ import annotations

import html as _html
import http.cookiejar
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

MAX_BYTES = 400_000          # never read more than this from one page
TIMEOUT = 20                 # seconds, per request
DDG_HTML = "https://html.duckduckgo.com/html/?q="
DDG_LITE = "https://lite.duckduckgo.com/lite/?q="


class WebError(Exception):
    """Something went wrong that is worth telling the user about."""


# Many real sites (Google's developer docs among them) bounce you through a
# redirect that only completes if the cookie it just set is sent back. The
# stdlib opener keeps no cookies, so those pages fail with a bare "302"; a
# shared cookie-aware opener fixes that.
_COOKIES = http.cookiejar.CookieJar()
_OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(_COOKIES),
    urllib.request.HTTPRedirectHandler(),
)


# ---------------------------------------------------------------------------
# safety: public http/https only
# ---------------------------------------------------------------------------

def _host_ok(host: str) -> bool:
    """False for loopback, private, link-local and other non-public addresses."""
    if not host:
        return False
    host = host.strip("[]").lower().rstrip(".")
    if host in ("localhost", "localhost.localdomain"):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:                                             # noqa: BLE001
        return False
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
            return False
    return True


def normalize_url(url: str) -> str:
    """Turn whatever Anya or the user wrote into a safe, absolute http(s) URL."""
    url = (url or "").strip().strip("<>\"'`")
    if not url:
        raise WebError("no address was given")
    if url.startswith("//"):
        url = "https:" + url
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise WebError(f"only http and https links can be opened (not {parts.scheme or '?'})")
    if not _host_ok(parts.hostname or ""):
        raise WebError("that address isn't reachable from the app")
    return urllib.parse.urlunsplit(parts)


# ---------------------------------------------------------------------------
# fetching
# ---------------------------------------------------------------------------

def fetch(url: str, max_bytes: int = MAX_BYTES, timeout: int = TIMEOUT) -> dict:
    """GET a URL. Returns {url, final_url, content_type, text, truncated}."""
    url = normalize_url(url)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": ("text/html,application/xhtml+xml,application/json;q=0.9,"
                   "text/plain;q=0.8,*/*;q=0.5"),
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            raw = resp.read(max_bytes + 1)
            final = resp.url or url
            ctype = resp.headers.get("Content-Type", "") or ""
            charset = resp.headers.get_content_charset()
    except urllib.error.HTTPError as exc:
        raise WebError(f"the site answered with HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise WebError(f"couldn't reach the site ({exc.reason})") from None
    except WebError:
        raise
    except Exception as exc:                                      # noqa: BLE001
        raise WebError(f"the request failed ({type(exc).__name__}: {exc})") from None

    body = raw[:max_bytes]
    if charset:
        try:
            text = body.decode(charset, "replace")
        except LookupError:
            text = body.decode("utf-8", "replace")
    else:
        text = _decode(body)
    return {"url": url, "final_url": final, "content_type": ctype,
            "text": text, "truncated": len(raw) > max_bytes}


def _decode(body: bytes) -> str:
    """Best-effort decode when the header had no charset: sniff the document."""
    m = re.search(rb"""(?i)charset\s*=\s*["']?([\w-]+)""", body[:4096])
    if m:
        try:
            return body.decode(m.group(1).decode("ascii", "ignore"), "replace")
        except LookupError:
            pass
    return body.decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# html -> readable text
# ---------------------------------------------------------------------------

_DROP = re.compile(r"(?is)<(script|style|noscript|svg|canvas|template|iframe|"
                   r"nav|header|footer|form|aside|button)\b[^>]*>.*?</\1\s*>")
_COMMENT = re.compile(r"(?s)<!--.*?-->")
_BREAK = re.compile(r"(?i)</?(p|div|br|li|tr|h[1-6]|section|article|blockquote|"
                    r"pre|ul|ol|dl|dt|dd|table|thead|tbody|td|th|hr)\b[^>]*>")
_TAG = re.compile(r"""(?s)<(?:"[^"]*"|'[^']*'|[^'">])*>""")
_SPACE = re.compile(r"[ \t\u00a0\f\v]+")
_BLANK = re.compile(r"\n{3,}")


_MAIN = re.compile(r"(?is)<(main|article)\b[^>]*>(.*?)</\1\s*>")


def _main_content(raw: str) -> str:
    """Prefer the page's <main>/<article> body over menus and sidebars."""
    m = _MAIN.search(raw)
    if m and len(m.group(2)) > 800:
        return m.group(2)
    return raw


def html_to_text(raw: str) -> str:
    s = _COMMENT.sub(" ", raw)
    s = _DROP.sub(" ", s)
    s = _BREAK.sub("\n", s)
    s = _TAG.sub(" ", s)
    s = _html.unescape(s)
    s = _SPACE.sub(" ", s)
    s = "\n".join(line.strip() for line in s.splitlines())
    return _BLANK.sub("\n\n", s).strip()


def _clean(fragment: str) -> str:
    return _SPACE.sub(" ", _html.unescape(_TAG.sub("", fragment))).strip()


def _title_of(raw: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    return _clean(m.group(1))[:200] if m else ""


def page_text(url: str, max_chars: int = 1400) -> dict:
    """Fetch a page and reduce it to something that fits Anya's context window."""
    got = fetch(url)
    ctype = (got["content_type"] or "").lower()
    raw = got["text"]
    head = raw[:2000].lower()
    if "html" in ctype or "<html" in head or "<body" in head:
        title = _title_of(raw) or got["final_url"]
        text = html_to_text(_main_content(raw))
    else:                                                        # json / plain text
        title = got["final_url"]
        text = raw.strip()
    text = _SPACE.sub(" ", text.replace("\r", "\n").replace("\n", " \n")).strip()
    if len(text) > max_chars:
        cut = text[:max_chars]
        if " " in cut:
            cut = cut[:cut.rfind(" ")]
        text = cut.rstrip() + " …(page truncated)"
    return {"title": title, "url": got["final_url"], "text": text,
            "truncated": got["truncated"] or "(page truncated)" in text}


# ---------------------------------------------------------------------------
# search (DuckDuckGo HTML endpoint — free, no key)
# ---------------------------------------------------------------------------

def _real_url(href: str) -> str:
    """DDG wraps results as //duckduckgo.com/l/?uddg=<encoded real url>."""
    if "uddg=" in href:
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)
        if qs.get("uddg"):
            href = qs["uddg"][0]
    if href.startswith("//"):
        href = "https:" + href
    return _html.unescape(href)


_RESULT_A = re.compile(r'(?is)<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>')
_SNIPPET = re.compile(r'(?is)class="result__snippet"[^>]*>(.*?)(?:</a>|</div>)')
_LITE_A = re.compile(r"""(?is)<a[^>]*class=["']result-link["'][^>]*href="([^"]+)"[^>]*>(.*?)</a>""")
_LITE_S = re.compile(r"""(?is)class=["']result-snippet["'][^>]*>(.*?)(?:</td>|</a>)""")


def _from_ddg(query: str, limit: int, lite: bool = False) -> list[dict]:
    base, cap = (DDG_LITE, 300_000) if lite else (DDG_HTML, 400_000)
    page = fetch(base + urllib.parse.quote_plus(query), max_bytes=cap, timeout=25)["text"]
    anchors = _LITE_A.findall(page) if lite else _RESULT_A.findall(page)
    snippets = _LITE_S.findall(page) if lite else _SNIPPET.findall(page)

    out: list[dict] = []
    for i, (href, title) in enumerate(anchors):
        try:
            url = normalize_url(_real_url(href))
        except WebError:
            continue
        if i < len(snippets):
            snippet = _clean(snippets[i])
        else:
            snippet = ""
        out.append({"title": _clean(title)[:140] or url, "url": url,
                    "snippet": snippet[:300]})
        if len(out) >= limit:
            break
    return out


def search(query: str, max_results: int = 6) -> list[dict]:
    """Search the web. Tries DuckDuckGo's HTML endpoint, then its Lite one."""
    query = (query or "").strip()
    if not query:
        raise WebError("no search words were given")
    problems = []
    for lite in (False, True):
        try:
            hits = _from_ddg(query, max_results, lite=lite)
        except WebError as exc:
            problems.append(str(exc))
            continue
        if hits:
            return hits
        problems.append("no results")
    raise WebError("the search didn't work (" + "; ".join(dict.fromkeys(problems)) + ")")


# ---------------------------------------------------------------------------
# the tool protocol
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"'`)\]}\u201d]+")


def find_urls(text: str, limit: int = 3) -> list[str]:
    """Public links the user typed, normalised and de-duplicated."""
    out: list[str] = []
    for m in _URL_RE.finditer(text or ""):
        raw = m.group(0).rstrip(".,;:!?")
        if raw.lower().startswith("www."):
            raw = "https://" + raw
        try:
            url = normalize_url(raw)
        except WebError:
            continue
        if url not in out:
            out.append(url)
        if len(out) >= limit:
            break
    return out


# Anya is a 1.5B model: left to decide for herself she will sometimes answer from
# memory instead of searching. So an explicit "search the web for X" is treated as
# an instruction and run before she is even asked — the same way a pasted link is.
_SEARCH_INTENT = re.compile(
    r"(?i)\b(?:web[\s-]?search|search\s+(?:the\s+)?(?:web|internet|online)|search\s+for"
    r"|google|look\s+(?:it|this|that)?\s*up(?:\s+online)?|find\s+(?:it\s+)?online"
    r"|look\s+online|check\s+online)\b")

_STRIP_TRIGGER = re.compile(
    r"(?i)\b(?:please\s+)?(?:web[\s-]?search|search\s+(?:the\s+)?(?:web|internet|online)"
    r"|search\s+for|google|look\s+(?:it|this|that)?\s*up(?:\s+online)?"
    r"|find\s+(?:it\s+)?online|look\s+online|check\s+online)\b")

# Questions about things that change are the ones a small model is most confidently
# wrong about, so they get looked up too. Two triggers, both narrow on purpose:
#   * a recency word  ("newest version")  *plus*  a fact word ("version")
#   * a topic that is live by nature      ("weather", "how much does X cost")
_RECENT = re.compile(r"(?i)\b(latest|newest|most recent|current|up[\s-]to[\s-]date"
                     r"|this (?:year|month|week))\b")
_FACTY = re.compile(r"(?i)\b(version|release[sd]?|price[sd]?|cost|news|update[sd]?"
                    r"|sdk|api level|stable|download|changelog|docs|documentation"
                    r"|when (?:was|is|did|does)|how many)\b")
_LIVE = re.compile(r"(?i)\b(weather|forecast|stock price|share price|exchange rate"
                   r"|release date|how much|who won|news)\b")


def wants_search(text: str) -> bool:
    """When should the app search on her behalf?

    Either the message asks for one outright ("search the web for X"), or it asks
    about something that changes — "the newest version of X", "how much does it
    cost" — which is exactly where a 1.5B model answers from stale memory with
    total confidence. Both are cheap to get right by just looking.

    A plain "search the web for ..." always works, whatever this decides.
    """
    text = text or ""
    if _SEARCH_INTENT.search(text) or _LIVE.search(text):
        return True
    return bool(_RECENT.search(text) and _FACTY.search(text))


def search_query_from(text: str) -> str:
    """Turn "can you search the web for X, and cite sources?" into "X"."""
    q = _URL_RE.sub(" ", text or "")
    q = re.sub(r"(?i)^\s*(?:hey\s+)?(?:can|could|would|will)\s+you\s+", "", q)
    q = re.sub(r"(?i)^\s*(?:please\s+|pls\s+)?", "", q)
    q = _STRIP_TRIGGER.sub(" ", q)
    q = re.sub(r"(?i)^\s*(?:please\s+)?(?:for|about|regarding|on the web|online|on)\s+", "", q)
    q = re.sub(r"(?i)^\s*(?:what(?:'s| is| are)|who(?:'s| is)|how much|how many|"
               r"when (?:was|is|did|does)|when|where|why|how|tell me|find)\b\s*", "", q)
    q = re.sub(r"(?i)^\s*(?:does|do|did|is|are|was|were|has|have)\s+", "", q)
    q = re.sub(r"(?i)[,;]?\s*(?:and\s+)?(?:please\s+)?(?:cite|quote|give|show|list|"
               r"include|tell me|explain)\b.*$", "", q)
    q = re.sub(r"\s+", " ", q).strip(" ,.;:-?!")
    if not q:
        q = re.sub(r"\s+", " ", (text or "").strip())[:200]
    return q[:200]


def _json_objects(text: str):
    """Every JSON object that occurs anywhere in the text (fences and all)."""
    dec = json.JSONDecoder()
    i = 0
    while True:
        i = text.find("{", i)
        if i < 0:
            return
        try:
            obj, end = dec.raw_decode(text, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict):
            yield obj
        i = max(end, i + 1)


_SEARCH_WORDS = {"web_search", "websearch", "search", "search_web", "google", "lookup"}
_OPEN_WORDS = {"web_open", "webopen", "open", "open_url", "fetch", "read",
               "read_url", "browse", "visit", "goto"}


def parse_tool_call(text: str) -> dict | None:
    """Find a {"name": ..., "arguments": {...}} block and turn it into an action.

    Returns {"name": "web_search", "query": ...} or {"name": "web_open", "url": ...},
    or None when the reply is an ordinary answer.
    """
    for obj in _json_objects(text or ""):
        name = obj.get("name") or obj.get("tool") or obj.get("action")
        args = obj.get("arguments") or obj.get("args") or obj.get("parameters") or {}
        if isinstance(name, dict):                    # {"function": {"name": ...}}
            args = name.get("arguments", args)
            name = name.get("name")
        if not isinstance(name, str):
            continue
        if not isinstance(args, dict):
            args = {}
        key = name.strip().lower()
        if key in _SEARCH_WORDS:
            q = args.get("query") or args.get("q") or args.get("search") or obj.get("query")
            if isinstance(q, str) and q.strip():
                return {"name": "web_search", "query": q.strip()[:300]}
        if name.lower() in _OPEN_WORDS:
            u = args.get("url") or args.get("link") or obj.get("url")
            if isinstance(u, str) and u.strip():
                return {"name": "web_open", "url": u.strip()}
    return None
