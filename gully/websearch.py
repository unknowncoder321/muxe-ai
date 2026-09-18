"""
MUXE — web search, stdlib only (urllib). No requests, no deps, no API keys.
Uses DuckDuckGo HTML + Instant Answer endpoints. Fully graceful: any failure
returns [] and the caller continues without results. If `offline: true` in
config.yaml, this is disabled entirely.
"""
from __future__ import annotations

import html
import json
import re
import socket
import urllib.parse
import urllib.request
from typing import List

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_TIMEOUT = 6  # seconds per request


def _fetch(url: str, timeout: int = _TIMEOUT) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).strip()


def search(query: str, max_results: int = 5) -> List[dict]:
    """Return [{'title','url','snippet'}]. Empty list on any failure/offline."""
    q = (query or "").strip()
    if not q:
        return []
    results: List[dict] = []

    # 1) DuckDuckGo HTML endpoint (best snippets)
    try:
        page = _fetch("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(q))
        for m in re.finditer(
                r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
                r'.*?class="result__snippet"[^>]*>(.*?)</a>',
                page, re.S):
            url = m.group(1)
            # ddg redirect wrap: //duckduckgo.com/l/?uddg=<encoded>
            if "uddg=" in url:
                try:
                    url = urllib.parse.unquote(
                        re.search(r"uddg=([^&]+)", url).group(1))
                except Exception:
                    pass
            if url.startswith("//"):
                url = "https:" + url
            title = _strip_tags(m.group(2))
            snip = _strip_tags(m.group(3))
            if title:
                results.append({"title": title[:110], "url": url, "snippet": snip[:240]})
            if len(results) >= max_results:
                break
    except Exception:
        pass

    # 2) Instant Answer API as top-up
    if len(results) < max_results:
        try:
            raw = _fetch("https://api.duckduckgo.com/?format=json&no_html=1&skip_disambig=1&q="
                         + urllib.parse.quote(q))
            data = json.loads(raw)
            if data.get("AbstractText"):
                results.insert(0, {
                    "title": (data.get("Heading") or q)[:110],
                    "url": (data.get("AbstractURL") or "")[:200],
                    "snippet": data["AbstractText"][:240],
                })
            for t in (data.get("RelatedTopics") or []):
                if isinstance(t, dict) and t.get("Text"):
                    results.append({
                        "title": t["Text"][:110],
                        "url": (t.get("FirstURL") or "")[:200],
                        "snippet": t["Text"][:240],
                    })
                if len(results) >= max_results:
                    break
        except Exception:
            pass

    # dedupe by url
    seen, out = set(), []
    for r in results:
        u = r.get("url") or ""
        if u and u in seen:
            continue
        seen.add(u)
        out.append(r)
    return out[:max_results]


def format_results(results: List[dict], max_chars: int = 900) -> str:
    """Compact context block to feed into the prompt. Empty string if nothing."""
    if not results:
        return ""
    lines = []
    used = 0
    for r in results:
        row = f"- {r['title']}" + (f" — {r['snippet']}" if r.get("snippet") else "")
        if used + len(row) > max_chars:
            break
        lines.append(row)
        used += len(row)
    return "Web results:\n" + "\n".join(lines)


def is_online(timeout: float = 1.5) -> bool:
    """Cheap reachability probe (1.1.1.1:443). Never raises."""
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=timeout).close()
        return True
    except Exception:
        return False
