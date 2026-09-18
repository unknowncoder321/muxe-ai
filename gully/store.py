"""
GULLY — conversation storage (local JSON files).
No DB, no embeddings, no memory-heavy deps. Just files on disk.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import re
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

from .config import CONVERSATIONS_DIR


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _slug(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:max_len].strip("-") or "chat")


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant" | "thinking" (internal)
    content: str
    ts: str = field(default_factory=_now_iso)
    # optional: expanded thinking trace for the last assistant reply
    thinking: str | None = None
    thoughts_visible: bool = False

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = asdict(self)
        # strip None to keep old files small
        if d.get("thinking") is None:
            d.pop("thinking", None)
        if not d.get("thoughts_visible"):
            d.pop("thoughts_visible", None)
        return d


@dataclass
class Conversation:
    id: str
    title: str
    created_at: str
    updated_at: str
    messages: list[Message] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [m.to_dict() for m in self.messages],
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Conversation":
        raw_msgs = d.get("messages", [])
        msgs: list[Message] = []
        for m in raw_msgs:  # type: ignore[arg-type]
            try:
                msgs.append(Message(
                    role=m.get("role", "user"),
                    content=m.get("content", ""),
                    ts=m.get("ts", _now_iso()),
                    thinking=m.get("thinking"),
                    thoughts_visible=bool(m.get("thoughts_visible", False)),
                ))
            except Exception:
                try:
                    msgs.append(Message(**{k: v for k, v in m.items() if k in ("role","content","ts","thinking","thoughts_visible")}))  # type: ignore[arg-type]
                except Exception:
                    continue
        return Conversation(
            id=d.get("id", uuid.uuid4().hex[:8]),
            title=d.get("title", "Chat"),
            created_at=d.get("created_at", _now_iso()),
            updated_at=d.get("updated_at", _now_iso()),
            messages=msgs,
        )


def _conv_path(cid: str) -> pathlib.Path:
    # sanitize id
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", cid)[:64] or uuid.uuid4().hex[:8]
    return CONVERSATIONS_DIR / f"{safe}.json"


def list_conversations() -> list[dict[str, Any]]:
    """Lightweight listing (no message bodies), newest first."""
    out: list[dict[str, Any]] = []
    if not CONVERSATIONS_DIR.exists():
        return out
    for p in CONVERSATIONS_DIR.glob("*.json"):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            c = Conversation.from_dict(raw)
            out.append(
                {
                    "id": c.id,
                    "title": c.title,
                    "created_at": c.created_at,
                    "updated_at": c.updated_at,
                    "message_count": len(c.messages),
                    "preview": (c.messages[-1].content[:80] if c.messages else ""),
                }
            )
        except Exception:
            continue
    out.sort(key=lambda x: x["updated_at"], reverse=True)
    return out


def load_conversation(cid: str) -> Conversation | None:
    p = _conv_path(cid)
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return Conversation.from_dict(raw)
    except Exception:
        return None


def save_conversation(conv: Conversation) -> None:
    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
    conv.updated_at = _now_iso()
    if not conv.title or conv.title.strip() in ("", "Chat", "New chat"):
        # auto-title from first user message
        for m in conv.messages:
            if m.role == "user" and m.content.strip():
                conv.title = _slug(m.content, 40).replace("-", " ").title() or conv.title
                # keep short
                if len(conv.title) > 48:
                    conv.title = conv.title[:48]
                break
    p = _conv_path(conv.id)
    # atomic-ish write
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(conv.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def create_conversation(title: str = "New chat", system_prompt: str | None = None) -> Conversation:
    cid = uuid.uuid4().hex[:8]
    now = _now_iso()
    msgs: list[Message] = []
    if system_prompt:
        msgs.append(Message(role="system", content=system_prompt))
    conv = Conversation(id=cid, title=title, created_at=now, updated_at=now, messages=msgs)
    save_conversation(conv)
    return conv


def delete_conversation(cid: str) -> bool:
    p = _conv_path(cid)
    if p.exists():
        try:
            p.unlink()
            return True
        except Exception:
            return False
    return False
