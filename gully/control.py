"""
MUXE — file ops only (Claude Code style).
Just create files & folders. Nothing else.
Max: write files anywhere you say, max like Claude Code.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
_LAST_FOLDER: Optional[Path] = None

_BLOCKED = [
    Path("C:/Windows"),
    Path("C:/Program Files"),
    Path("C:/Program Files (x86)"),
    Path(os.environ.get("SystemRoot", "C:/Windows")),
]

def _is_safe(p: Path) -> bool:
    try:
        rp = p.resolve()
    except Exception:
        rp = p
    for b in _BLOCKED:
        try:
            if rp.is_relative_to(b):
                return False
        except Exception:
            if str(rp).lower().startswith(str(b).lower()):
                return False
    if str(rp).lower() in ("c:\\", "c:/"):
        return False
    return True

def _resolve(raw: str) -> Path:
    s = raw.strip().strip('"').strip("'").rstrip(".!,;")
    low = s.lower()
    if low in ("it", "that", "this folder", "the folder"):
        if _LAST_FOLDER and _LAST_FOLDER.exists():
            return _LAST_FOLDER
        return Path.home() / "Desktop" / "muxe-temp"
    if re.match(r"^[a-zA-Z]:[\\/]", s) or s.startswith("\\\\") or s.startswith("/"):
        return Path(s)
    desktop = Path.home() / "Desktop"
    documents = Path.home() / "Documents"
    m = re.search(r"(.+?)\s+on\s+desktop\s*$", s, re.I)
    if m:
        name = re.sub(r"^(?:a\s+)?folder\s+(?:named\s+|called\s+)?", "", m.group(1).strip(), flags=re.I).strip().strip('"\'')
        return desktop / name if name else desktop
    m = re.search(r"(.+?)\s+in\s+documents\s*$", s, re.I)
    if m:
        name = re.sub(r"^(?:a\s+)?folder\s+(?:named\s+|called\s+)?", "", m.group(1).strip(), flags=re.I).strip()
        return documents / name if name else documents
    cleaned = re.sub(r"^(?:a\s+)?(?:folder|file|directory)\s+(?:named\s+|called\s+)?", "", s, flags=re.I).strip().strip('"\'')
    if not cleaned:
        cleaned = s
    if "/" in cleaned or "\\" in cleaned:
        p = Path(cleaned)
        return p if p.is_absolute() else desktop / cleaned
    return desktop / cleaned if cleaned else desktop

def create_folder(target: str) -> str:
    global _LAST_FOLDER
    p = _resolve(target)
    if not _is_safe(p):
        return f"blocked: system folder -> {p}"
    try:
        p.mkdir(parents=True, exist_ok=True)
        _LAST_FOLDER = p
        return f"created folder -> {p}"
    except Exception as e:
        return f"create folder failed: {e}"

def create_file(path: str, content: str = "") -> str:
    global _LAST_FOLDER
    p = _resolve(path)
    if not _is_safe(p):
        return f"blocked: system path -> {p}"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        _LAST_FOLDER = p.parent
        return f"created file -> {p}"
    except Exception as e:
        return f"create file failed: {e}"

def get_last_folder() -> Optional[Path]:
    return _LAST_FOLDER

def set_last_folder(p: Path) -> None:
    global _LAST_FOLDER
    _LAST_FOLDER = p

def save_generated_files(text: str, base: Optional[Path] = None) -> list[Path]:
    if not text or "FILE:" not in text:
        return []
    folder = base or _LAST_FOLDER or Path.home() / "Desktop"
    saved: list[Path] = []
    pat = re.compile(r"FILE:\s*([^\n`]+?)\s*\n```(?:\w+)?\s*\n(.*?)\n```", re.S | re.I)
    for m in pat.finditer(text):
        rel = m.group(1).strip().strip('"\'')
        rel = re.sub(r"^\.[\\/]+", "", rel)
        target = folder / rel if not Path(rel).is_absolute() else Path(rel)
        if not _is_safe(target):
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(m.group(2), encoding="utf-8")
            saved.append(target)
        except Exception:
            continue
    return saved

# ---- only file/folder actions ----
_PATTERNS = [
    (re.compile(r"\b(?:create|make)\s+(?:a\s+)?folder\s+(?:named\s+|called\s+)?[\"']?(.+?)[\"']?\s*$", re.I), lambda m: create_folder(m.group(1))),
    (re.compile(r"\b(?:create|make)\s+(?:a\s+)?file\s+[\"']?(.+?)[\"']?\s*$", re.I), lambda m: create_file(m.group(1), "")),
]

def try_action(text: str) -> Optional[str]:
    t = text.strip()
    if not t or len(t) > 800:
        return None
    if t.startswith(("/", "?", "#", "```")):
        return None
    for pat, fn in _PATTERNS:
        m = pat.search(t)
        if m:
            try:
                return fn(m)
            except Exception as e:
                return f"failed: {e}"
    return None

def list_actions() -> list[tuple[str, str]]:
    return [
        ("create folder my-app", "new folder on Desktop"),
        ("create folder X on desktop", "explicit Desktop"),
        ("create file notes.txt", "empty file"),
        ("FILE: app.py + code block", "LLM auto-saves files (Claude Code style)"),
    ]

def llm_action_prompt(user_text: str) -> str:
    return user_text
