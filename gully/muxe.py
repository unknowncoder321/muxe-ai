"""
MUXE — terminal welcome screen built to match the reference layout exactly:
coral box with title, centered left column (welcome + mascot + footer + path),
coral vertical divider, right column (Tips / Recent), then
/model line, rule, "> Try ..." with block cursor, rule, "? for shortcuts".

Raw ANSI drawing (not rich tables) so every column lands exactly where intended.
Animated mascot lives in the left column and never shifts the layout.
Offline, CPU-only, local.
Now with Claude-style thinking (token-by-token, clickable/t-to-expand) and
ChatGPT-style token-by-token answer streaming.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import os
import threading
from dataclasses import asdict
from typing import Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
except Exception:
    pass

HAS_RICH = False
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.text import Text
    from rich.panel import Panel
    from rich.table import Table
    from rich.box import ROUNDED
    from rich.live import Live
    HAS_RICH = True
except Exception:
    HAS_RICH = False
    Console = None  # type: ignore
    Text = None  # type: ignore
    Panel = None  # type: ignore
    Table = None  # type: ignore
    ROUNDED = None  # type: ignore
    Live = None  # type: ignore

try:
    from .config import load_config, load_persona
    from .engine import create_engine, history_to_text, history_to_text_smart, estimate_tokens, thinking_trace
    from .websearch import search as web_search, format_results as format_web, is_online as web_is_online
    from .control import try_action as pc_try_action, list_actions as pc_list_actions
    from .store import (
        Conversation, Message,
        create_conversation, delete_conversation,
        list_conversations, load_conversation, save_conversation,
    )
    from . import __version__ as _ver
except ImportError:
    import pathlib as _pl, sys as _sys
    _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
    from gully.config import load_config, load_persona  # type: ignore
    from gully.engine import create_engine, history_to_text, history_to_text_smart, estimate_tokens, thinking_trace  # type: ignore
    from gully.websearch import search as web_search, format_results as format_web, is_online as web_is_online  # type: ignore
    from gully.control import try_action as pc_try_action, list_actions as pc_list_actions  # type: ignore
    from gully.store import (  # type: ignore
        Conversation, Message,
        create_conversation, delete_conversation,
        list_conversations, load_conversation, save_conversation,
    )
    try:
        from gully import __version__ as _ver  # type: ignore
    except Exception:
        _ver = "0.1.0"

# ---------------- palette (raw ANSI, truecolor) ----------------
CORAL   = "\x1b[38;2;255;127;107m"
CORAL_B = "\x1b[38;2;255;90;50m"
DIM     = "\x1b[2m"
NO_DIM  = "\x1b[22m"
WHITE   = "\x1b[97m"
BOLD    = "\x1b[1m"
RST     = "\x1b[0m"

# ---------------- mascot (8 wide, 5 tall — fixed size so layout never moves) ----------------
IDLE = [
    ["  ▄▄▄▄▄▄  ", " ▐ ◉  ◉ ▌ ", " ▐  ▿▿  ▌ ", " ▐██████▌ ", "  ▀▀  ▀▀  "],
    ["  ▄▄▄▄▄▄  ", " ▐ ◐  ◉ ▌ ", " ▐  ▿▿  ▌ ", " ▐██████▌ ", "  ▀▀  ▀▀  "],
    ["  ▄▄▄▄▄▄  ", " ▐ ─  ─ ▌ ", " ▐  ▿▿  ▌ ", " ▐██████▌ ", "  ▀▀  ▀▀  "],
    ["  ▄▄▄▄▄▄  ", " ▐ ◑  ◉ ▌ ", " ▐  ▿▿  ▌ ", " ▐██████▌ ", "  ▀▀  ▀▀  "],
    ["  ▄▄▄▄▄▄  ", " ▐ ◉  ◉ ▌ ", " ▐  ▿▿  ▌ ", " ▐██████▌ ", "  ▄▄  ▄▄  "],
]
THINK = [
    ["  ▄▄▄▄▄▄  ", " ▐ ◐  ◉ ▌ ", " ▐  ··  ▌ ", " ▐██████▌ ", "  ▀▀  ▀▀  "],
    ["  ▄▄▄▄▄▄  ", " ▐ ◑  ◉ ▌ ", " ▐ ···  ▌ ", " ▐██████▌ ", "  ▀▀  ▀▀  "],
    ["  ▄▄▄▄▄▄  ", " ▐ ◒  ◉ ▌ ", " ▐ ···· ▌ ", " ▐██████▌ ", "  ▀▀  ▀▀  "],
    ["  ▄▄▄▄▄▄  ", " ▐ ◓  ◉ ▌ ", " ▐ ···  ▌ ", " ▐██████▌ ", "  ▀▀  ▀▀  "],
]
TURBO_A = ["  ▄▄▄▄▄▄  ", " ▐ ◉  ◉ ▌ ", " ▐  ▿▿  ▌ ", " ▐██████▌ ", "  ▀▀  ▀▀  "]
TURBO_B = ["  ▄▄▄▄▄▄  ", " ▐ ◎  ◎ ▌ ", " ▐  ▿▿  ▌ ", " ▐██████▌ ", " ▐▀▀  ▀▀▌ "]
BOOT = [
    ["  ▓▓▓▓▓▓  ", " ▐ ◉  ◉ ▌ ", " ▐  ▿▿  ▌ ", " ▐▓▓▓▓▓▓▌ ", "  ▀▀  ▀▀  "],
    ["  ▓▓▓▓▓▓  ", " ▐ ◉  ◉ ▌ ", " ▐  ▿▿  ▌ ", " ▐▓▓▓▓▓▓▌ ", "  ▄▄  ▄▄  "],
    ["  ▄▄▄▄▄▄  ", " ▐ ◉  ◉ ▌ ", " ▐  ▿▿  ▌ ", " ▐██████▌ ", "  ▄▄  ▄▄  "],
    ["  ▄▄▄▄▄▄  ", " ▐ ◉  ◉ ▌ ", " ▐  ▿▿  ▌ ", " ▐██████▌ ", "  ▀▀  ▀▀  "],
]
MASCOT_W = 10
MASCOT_H = 5

# position of the mascot while sitting at the prompt line
_GHOST = {"up": 0, "col": 1, "at_prompt": False}
_lock = threading.Lock()
_in_ghost = False
_original_stdout_write = None
_original_stderr_write = None
_auto_console_ref = None
_term_col = 0


def _install_auto_bump(console):
    """Hook stdout/stderr so every physical scroll increments _GHOST['up'].
    Ghost draws and the temporary meter use save/restore and are bypassed.
    """
    global _original_stdout_write, _original_stderr_write, _auto_console_ref, _term_col
    if _original_stdout_write is not None:
        _auto_console_ref = console
        return
    _auto_console_ref = console
    _original_stdout_write = sys.stdout.write
    _original_stderr_write = sys.stderr.write
    _term_col = 0

    def _bump_for_text(text: str):
        global _term_col
        if not text:
            return
        w = 80
        try:
            if _auto_console_ref is not None:
                w = int(getattr(_auto_console_ref, "width", 80) or 80)
            else:
                try:
                    w = os.get_terminal_size().columns
                except Exception:
                    w = 80
        except Exception:
            w = 80
        if w <= 0:
            w = 80
        # Fast path: plain printable text (the common case — every streamed token)
        # has no newline/escape/control chars, so the char loop below is pure
        # overhead. Do the wrap math directly instead of walking each character.
        if text.isprintable():
            total = _term_col + len(text)
            _term_col = total % w
            if total >= w:
                _GHOST["up"] += total // w
            return
        delta = 0
        col = _term_col
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if ch == "\x1b" and i + 1 < n and text[i + 1] == "[":
                j = i + 2
                while j < n and text[j] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz":
                    j += 1
                if j < n:
                    j += 1
                i = j
                continue
            elif ch == "\n":
                delta += 1
                col = 0
            elif ch == "\r":
                col = 0
            elif ch == "\b":
                col = max(0, col - 1)
            elif ch == "\t":
                col = ((col // 8) + 1) * 8
                if col >= w:
                    delta += col // w
                    col = col % w
            elif ch == "\x00":
                pass
            else:
                if ch >= " ":
                    col += 1
                    if col >= w:
                        delta += 1
                        col = 0
            i += 1
        _term_col = col
        if delta:
            try:
                _GHOST["up"] += delta
            except Exception:
                pass

    def _wrap_out(text):
        if _in_ghost:
            return _original_stdout_write(text)
        try:
            _bump_for_text(text)
        except Exception:
            pass
        return _original_stdout_write(text)

    def _wrap_err(text):
        if _in_ghost:
            return _original_stderr_write(text)
        try:
            _bump_for_text(text)
        except Exception:
            pass
        return _original_stderr_write(text)

    sys.stdout.write = _wrap_out  # type: ignore
    sys.stderr.write = _wrap_err  # type: ignore


def _app(cfg) -> str:
    n = (getattr(cfg, "app_name", "") or "").strip()
    return "MUXE" if (not n or n.upper() == "GULLY") else n


def _user_name() -> str:
    for k in ("MUXE_USER", "USERNAME", "USER"):
        v = os.environ.get(k)
        if v and v.strip():
            return v.strip().split("\\")[-1]
    return "Diego"


_QUANT_RE = re.compile(r"[-_.](?:I?Q\d(?:_[A-Z0-9]+)*|BF16|FP?16|FP?32)$", re.I)
_NOISE_TAGS = ("-Instruct", "-instruct", "-Chat", "-chat", "-GGUF", "-gguf", "-HF")


def _pretty_model(mid: str, maxlen: int = 18) -> str:
    """Clean display name from a model path/id.
    'gully/models/Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf' -> 'Qwen2.5-Coder 1.5B'."""
    base = (mid or "").replace("\\", "/").split("/")[-1].strip()
    if base.lower().endswith(".gguf"):
        base = base[:-5]
    base = _QUANT_RE.sub("", base)
    base = re.sub(r"[-_]\d{4}$", "", base)  # drop date/version tag, e.g. -2507
    for tag in _NOISE_TAGS:
        if base.endswith(tag):
            base = base[: -len(tag)]
    m = re.match(r"^(.*?)-(\d+(?:\.\d+)?[Bb])$", base)
    if m and m.group(1):
        base = f"{m.group(1)} {m.group(2)}"
    base = base.strip("-_ .")
    return base[:maxlen] if len(base) > maxlen else base


def _model_name(eng, cfg) -> str:
    mid = getattr(eng, "model_id", getattr(cfg, "model_id", "")) or ""
    low = mid.lower()
    if not mid or "dummy" in low:
        return "MUXE Base"
    if "tinyllama" in low:
        return "TinyLlama 1.1B"
    # MUXE brand names for the models the installer ships
    for frag, name in (("qwen3-4b-instruct-2507", "MUXE 2.5 Pro"),
                       ("qwen2.5-coder-1.5b", "MUXE 1.5 Flash"),
                       ("qwen2.5-0.5b", "MUXE 1")):
        if frag in low:
            return name
    return _pretty_model(mid, 18) or "MUXE Base"


def _recent(n: int = 3):
    try:
        rows = [c for c in list_conversations() if c.get("message_count", 0) > 1]
        return rows[:n]
    except Exception:
        return []


def _ram_free_gb():
    """(free, total) in GB — WinAPI first, psutil fallback, None if unknown."""
    try:
        import ctypes

        class _MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        m = _MS()
        m.dwLength = ctypes.sizeof(_MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        if m.ullTotalPhys:
            return m.ullAvailPhys / (1024 ** 3), m.ullTotalPhys / (1024 ** 3)
    except Exception:
        pass
    try:
        import psutil
        vm = psutil.virtual_memory()
        return vm.available / (1024 ** 3), vm.total / (1024 ** 3)
    except Exception:
        return None, None


def _ago(ts: str) -> str:
    try:
        import datetime
        d = datetime.datetime.fromisoformat(ts)
        now = datetime.datetime.now(d.tzinfo) if d.tzinfo else datetime.datetime.now()
        s = max(0.0, (now - d).total_seconds())
        if s < 90:
            return "just now"
        if s < 3600:
            return f"{int(s // 60)}m ago"
        if s < 86400:
            return f"{int(s // 3600)}h ago"
        if s < 604800:
            return f"{int(s // 86400)}d ago"
        return d.strftime("%d %b")
    except Exception:
        return ""


def _cell(text: str, width: int, align: str = "center", color: str = "") -> str:
    """Pad text into exactly `width` visible chars."""
    if width <= 0:
        return ""
    t = text
    if len(t) > width:
        t = t[: width - 1] + "…" if width > 1 else t[:1]
    pad = width - len(t)
    if align == "center":
        l = pad // 2
        r = pad - l
    elif align == "right":
        l, r = pad, 0
    else:
        l, r = 0, pad
    body = " " * l + t + " " * r
    return f"{color}{body}{RST}" if color else body


def _rule(width: int) -> str:
    return f"{DIM}{'─' * max(0, width)}{RST}"


# ---------------- generation meter ----------------
BAR_W = 12


def _bar(frac: float, width: int = BAR_W) -> str:
    frac = 0.0 if frac < 0 else (1.0 if frac > 1.0 else frac)
    n = int(round(frac * width))
    return "▰" * n + "▱" * (width - n)


def _mmss(secs: float) -> str:
    s = int(max(0.0, secs))
    return f"{s // 60}:{s % 60:02d}"


def _meter_line(tokens: int, max_tokens: int, rate: float, secs: float, width: int) -> str:
    """Fixed-width progress row so the line never jitters between frames."""
    frac = (tokens / max_tokens) if max_tokens else 0.0
    s = (f"  {_bar(frac)}  {tokens:>4}/{max_tokens} tok"
         f"  ·  {rate:>5.1f} tok/s  ·  {_mmss(secs)}")
    return s[: max(1, width - 1)]


def build_screen(cfg, eng, width: int):
    """
    Returns (lines, mascot_index, mascot_col).
    """
    name = _app(cfg)
    ver = _ver or "0.1.0"
    model = _model_name(eng, cfg)
    title = f"{name} Code v{ver}"

    B = max(40, min(width - 2, 86))
    inner = B - 2
    left_w = int(round(inner * 0.47))
    if left_w < 26:
        left_w = 26
    div_w = 1
    right_w = max(18, inner - left_w - div_w)
    left_w = inner - div_w - right_w

    ram_free, ram_total = _ram_free_gb()
    recent = _recent(3)
    threads = int(getattr(cfg.gen, "threads", 0) or 0) or 4
    engine_name = getattr(eng, "name", cfg.engine)
    narrow = B < 64

    footer = f"{model} · local"
    if len(footer) > left_w - 2:
        footer = model
    left_lines = [
        "",
        f"Welcome back {_user_name()}!",
        "",
        None, None, None, None, None,
        "",
        footer,
        f"~\\{name} Code",
        "",
    ]

    rcw = (inner if narrow else right_w)
    def _fit(s: str) -> str:
        return s[: max(1, rcw - 3)]

    right_lines = [
        "",
        "Quick start",
        _fit("  /new    fresh chat"),
        _fit("  /list   saved chats"),
        _fit("  /ghost  mascot dance"),
        "",
        "Recent",
    ]
    if recent:
        for c in recent:
            title_txt = (c.get("title") or "Untitled").strip()
            age = _ago(c.get("updated_at", ""))
            right_lines.append(_fit(f"  {title_txt} · {age}" if age else f"  {title_txt}"))
    else:
        right_lines.append(_fit("  Nothing yet — say hi"))

    rows = max(len(left_lines), len(right_lines))
    left_lines += [""] * (rows - len(left_lines))
    right_lines += [""] * (rows - len(right_lines))

    mascot_top_row = 3
    headers = {1, 6}
    content = []

    if narrow:
        for i in range(rows):
            if mascot_top_row <= i < mascot_top_row + MASCOT_H:
                cell = _cell(IDLE[0][i - mascot_top_row], inner, "center", CORAL)
            else:
                cell = _cell(left_lines[i] or "", inner, "center",
                             WHITE + BOLD if i == 1 else DIM)
            content.append(f"{CORAL}│{RST}{cell}{CORAL}│{RST}")
        content.append(f"{CORAL}│{RST}{DIM}{'─' * inner}{RST}{CORAL}│{RST}")
        for i, txt in enumerate(right_lines):
            style = CORAL + BOLD if i in headers else DIM
            cell = _cell(" " + (txt or ""), inner, "left", style)
            content.append(f"{CORAL}│{RST}{cell}{CORAL}│{RST}")
    else:
        for i in range(rows):
            if mascot_top_row <= i < mascot_top_row + MASCOT_H:
                cell = _cell(IDLE[0][i - mascot_top_row], left_w, "center", CORAL)
            else:
                cell = _cell(left_lines[i] or "", left_w, "center",
                             WHITE + BOLD if i == 1 else DIM)
            style = CORAL + BOLD if i in headers else DIM
            rcell = _cell(" " + (right_lines[i] or ""), right_w, "left", style)
            content.append(f"{CORAL}│{RST}{cell}{CORAL}│{RST}{rcell}{CORAL}│{RST}")

    t = len(title)
    dashes = max(0, B - 5 - t)
    top = f"{CORAL}╭─ {RST}{CORAL}{BOLD}{title}{RST}{CORAL} {'─' * dashes}╮{RST}"
    bot = f"{CORAL}╰{'─' * (B - 2)}╯{RST}"
    lines = [top] + content + [bot]

    prio = "HIGH" if os.name == "nt" else "nice"
    status1 = (f"  {engine_name} · ctx {cfg.gen.n_ctx} · max {cfg.gen.max_new_tokens} tok"
               f" · {threads} threads · {prio}")
    mode = "offline" if getattr(cfg, "offline", False) else "online"
    if ram_free is not None and ram_total:
        pct = int(round(100 * ram_free / ram_total)) if ram_total else 0
        status2 = (f"  RAM {ram_free:.1f} of {ram_total:.1f} GB free ({pct}%)"
                   f" · {cfg.max_history_turns}-turn memory · CPU only · {mode}")
    else:
        status2 = f"  {cfg.max_history_turns}-turn memory · CPU only · {mode}"

    lines.append("")
    lines.append(f"{CORAL}/model{RST}{DIM}  {model}{RST}")
    lines.append(f"{DIM}{status1}{RST}")
    lines.append(f"{DIM}{status2}{RST}")
    lines.append("")
    prompt_line = f"{CORAL}> {RST}{DIM}Try \"fix typecheck errors\"{RST} {WHITE}▌{RST}"
    lines.append(_rule(B))
    lines.append(prompt_line)
    lines.append(_rule(B))
    lines.append(f"{DIM}  ? shortcuts · /help all commands · /quit exit{RST}")

    mascot_index = 1 + mascot_top_row
    if narrow:
        mascot_col = 1 + 1 + max(0, (inner - MASCOT_W) // 2)
    else:
        mascot_col = 1 + 1 + max(0, (left_w - MASCOT_W) // 2)
    return lines, mascot_index, mascot_col


def _banner(console, cfg, eng) -> None:
    global _term_col
    width = console.width if console is not None else 80
    if console is None:
        lines, _, _ = build_screen(cfg, eng, min(80, width))
        import re as _re
        for ln in lines:
            print(_re.sub(r"\x1b\[[0-9;]*m", "", ln))
        return

    _install_auto_bump(console)
    lines, mi, col = build_screen(cfg, eng, width)
    sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.flush()
    _GHOST["up"] = len(lines) - mi
    _GHOST["col"] = col
    _GHOST["at_prompt"] = True
    _term_col = 0


def _draw(frame, bright=False) -> None:
    """Redraw the mascot in place. Only safe while the cursor sits on the prompt row."""
    global _in_ghost
    up, col = _GHOST["up"], _GHOST["col"]
    if up <= 0 or not _GHOST["at_prompt"]:
        return
    color = CORAL_B if bright else CORAL
    try:
        with _lock:
            _in_ghost = True
            out = [f"\x1b[s\x1b[{up}A\x1b[{col}G"]
            for i, row in enumerate(frame):
                out.append(f"{color}{row}{RST}")
                if i < len(frame) - 1:
                    out.append(f"\x1b[1B\x1b[{col}G")
            out.append("\x1b[u")
            if _original_stdout_write is not None:
                _original_stdout_write("".join(out))
            else:
                sys.stdout.write("".join(out))
            sys.stdout.flush()
    except Exception:
        pass
    finally:
        _in_ghost = False


def _boost_priority() -> None:
    try:
        import psutil
        p = psutil.Process()
        try:
            p.nice(psutil.HIGH_PRIORITY_CLASS)  # type: ignore
        except Exception:
            pass
        try:
            p.cpu_affinity(list(range(os.cpu_count() or 4)))
        except Exception:
            pass
    except Exception:
        try:
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(
                ctypes.windll.kernel32.GetCurrentProcess(), 0x80)
        except Exception:
            pass
    for k, v in {"OMP_NUM_THREADS": "4", "MKL_NUM_THREADS": "4",
                 "OPENBLAS_NUM_THREADS": "4", "NUMEXPR_NUM_THREADS": "4"}.items():
        try:
            os.environ[k] = v
        except Exception:
            pass
    # NOTE: deliberately NO torch import here. The active engine is llama_cpp, so
    # importing torch cost ~2.6s of startup and hundreds of MB of RAM for nothing.


def _console():
    if not HAS_RICH:
        return None
    try:
        # ANSI/animated UI only when stdout is a real terminal. Pipes stay plain text.
        if not sys.stdout.isatty():
            return None
        return Console(highlight=False, force_terminal=True, legacy_windows=False)  # type: ignore
    except Exception:
        return None


# ---------------- chat plumbing ----------------

def _slug(text: str, n: int = 40) -> str:
    s = text.strip().replace("\n", " ")
    return (s[:n] + "…") if len(s) > n else s


_FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.S)


def _code_blocks(text: str) -> list[str]:
    """Pull fenced code blocks out of a reply."""
    return [m.group(1) for m in _FENCE_RE.finditer(text or "")]


def _copy_text_windows(text: str) -> bool:
    """Put text on the Windows clipboard via Win32 directly.
    No subprocess — spawning powershell here killed the process silently."""
    try:
        import ctypes
        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.restype = ctypes.c_bool
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.CloseClipboard.restype = ctypes.c_bool

        data = text.encode("utf-16-le") + b"\x00\x00"
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h:
            return False
        ptr = kernel32.GlobalLock(h)
        if not ptr:
            kernel32.GlobalFree(h)
            return False
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(h)
        if not user32.OpenClipboard(None):
            kernel32.GlobalFree(h)
            return False
        try:
            user32.EmptyClipboard()
            if not user32.SetClipboardData(CF_UNICODETEXT, h):
                kernel32.GlobalFree(h)
                return False
            # on success the clipboard owns the handle — do not free it
        finally:
            user32.CloseClipboard()
        return True
    except Exception:
        return False


def _copy_to_clipboard(text: str) -> bool:
    """Best-effort clipboard copy."""
    if not text:
        return False
    if os.name == "nt":
        return _copy_text_windows(text)
    try:
        import subprocess
        for cmd in (["pbcopy"], ["xclip", "-selection", "clipboard"], ["xsel", "-b", "-i"]):
            try:
                subprocess.run(cmd, input=text.encode("utf-8"), check=True)
                return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _show_copy_hint(console) -> None:
    """Small copy affordance shown under a reply that contained code."""
    line = "  \u29c9  /copy"
    if console is None:
        print(line)
    else:
        console.print(Text(line, style="#ff7f6b"))


def _stream_plain(prompt, hist, eng, cfg) -> tuple[str, str]:
    """Piped/plain mode: token-by-token answer, nothing else."""
    thinking = ""
    try:
        thinking = thinking_trace(prompt, hist, getattr(eng, "persona", ""))
    except Exception:
        thinking = ""
    full = ""
    disp = _app(cfg).lower()
    sys.stdout.write(f"{disp} > ")
    sys.stdout.flush()
    try:
        for tok in eng.stream(prompt, hist):  # type: ignore
            full += tok
            sys.stdout.write(tok)
            sys.stdout.flush()
        sys.stdout.write("\n")
        sys.stdout.flush()
    except KeyboardInterrupt:
        sys.stdout.write("\n(interrupted)\n")
        sys.stdout.flush()
    except Exception as e:
        sys.stdout.write(f"\n[failed: {e}]\n")
        sys.stdout.flush()
        full += f"\n[failed: {e}]"
    return full, thinking


def _stream_tty(prompt, hist, eng, cfg, console) -> tuple[str, str, int]:
    """TTY: waits for the model, then streams the answer token-by-token as plain
    text — no token counts, no meters, no thinking noise."""
    # if called standalone (e.g. /web path) ensure ready
    try:
        _ready = getattr(eng, "is_ready", lambda: True)
        if not _ready():
            _spinner_for_engine(eng, cfg, _ready, getattr(console, "width", 80) or 80)
            if not _ready():
                thr = getattr(eng, "_warmup_thread", None)
                if thr is not None:
                    try: thr.join(timeout=30)
                    except Exception: pass
                if not _ready():
                    try: eng.warmup()  # type: ignore
                    except Exception: pass
    except Exception:
        pass
    global _in_ghost
    disp = _app(cfg).lower()

    _GHOST["at_prompt"] = False
    console.print(Text(f" {disp} ", style="bold white on #ff7f6b"), end=" ")
    sys.stdout.flush()

    # ---------- thinking: silent + instant (trace stored for memory, no UI) ----------
    thinking_buf = ""
    try:
        thinking_buf = thinking_trace(prompt, hist, getattr(eng, "persona", ""))
    except Exception:
        thinking_buf = ""

    # ---------- answer: plain text, streamed live. Nothing else. ----------
    full = ""
    t0 = time.time()
    try:
        for tok in eng.stream(prompt, hist):  # type: ignore
            full += tok
            sys.stdout.write(tok)
            sys.stdout.flush()
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        sys.stdout.flush()
        console.print(Text("  (interrupted — partial saved)", style="yellow"))
    except Exception as e:
        sys.stdout.write(f"\n[failed: {e}]\n")
        sys.stdout.flush()
        full += f"\n[failed: {e}]"

    sys.stdout.write("\n")
    sys.stdout.flush()
    elapsed = int((time.time() - t0) * 1000)
    # clean output: no token count, no stats line, no re-render. Just the text.
    if "```" in (full or ""):
        _show_copy_hint(console)
    return full, thinking_buf, elapsed


# ---- idle animation timeline (one clock, so it never drifts) ----
BLINK_PERIOD = 3.0
BLINK_STAGES = [
    (0.00, 1),
    (0.06, 2),
    (0.13, 3),
]
BLINK_END = 0.20
BREATHE_PERIOD = 1.5
PULSE_PERIOD = 2.4


def _idle_state(el: float):
    """Derive (frame, bright) from a single elapsed clock. Tight, no drift."""
    blink = el % BLINK_PERIOD
    if blink < BLINK_END:
        frame = IDLE[0]
        for off, fi in BLINK_STAGES:
            if blink >= off:
                frame = IDLE[fi]
        return frame, False
    breathe = int((el % BREATHE_PERIOD) / (BREATHE_PERIOD / 2)) % 2
    frame = IDLE[4] if breathe else IDLE[0]
    bright = ((el % PULSE_PERIOD) < (PULSE_PERIOD / 2))
    return frame, bright


def _input_line(console) -> str:
    prompt = f"{CORAL}> {RST}"
    try:
        import msvcrt
        if console is None or not sys.stdin.isatty():
            raise RuntimeError
    except Exception:
        _GHOST["at_prompt"] = True
        return input(prompt).strip()

    _GHOST["at_prompt"] = True
    sys.stdout.write(prompt)
    sys.stdout.flush()
    buf = ""
    t0 = time.monotonic()
    last_key = None
    try:
        while True:
            el = time.monotonic() - t0
            frame, bright = _idle_state(el)
            key = (id(frame), bright)
            if key != last_key:
                last_key = key
                _draw(frame, bright=bright)
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\r", "\n"):
                    _GHOST["at_prompt"] = False
                    sys.stdout.write("\r\n")
                    sys.stdout.flush()
                    return buf.strip()
                if ch == "\x03":
                    raise KeyboardInterrupt
                if ch == "\x1a":
                    raise EOFError
                if ch in ("\x08", "\x7f"):
                    if buf:
                        buf = buf[:-1]
                        sys.stdout.write("\b \b")
                        sys.stdout.flush()
                elif ch in ("\x00", "\xe0"):
                    try:
                        msvcrt.getwch()
                    except Exception:
                        pass
                elif ch >= " ":
                    buf += ch
                    sys.stdout.write(ch)
                    sys.stdout.flush()
                t0 = time.monotonic()
                last_key = None
            else:
                time.sleep(0.05)
    except BaseException:
        _GHOST["at_prompt"] = False
        raise


def _help(console):
    rows = [
        ("/help  /?", "shortcuts"),
        ("/new", "new chat"),
        ("/list", "saved chats"),
        ("/load <id>", "load a chat"),
        ("/clear", "clear screen"),
        ("/stats", "last generation stats"),
        ("/config", "model + settings"),
        ("/delete", "delete this chat"),
        ("/copy", "copy last code block (or /copy all)"),
        ("/ghost", "mascot dance"),
        ("/web <q>", "search web + answer"),
        ("/online", "turn web search on"),
        ("/offline", "local only, no network"),
        ("/do <action>", "run a PC action"),
        ("/actions", "list PC actions"),
        ("/think", "show last thinking"),
        ("/quit", "save and exit"),
    ]
    if console is None:
        for a, b in rows:
            print(f"  {a:<12} {b}")
        return
    t = Table(box=ROUNDED, show_header=False, pad_edge=False, border_style="#ff7f6b")
    t.add_column(style="bold #ff7f6b", no_wrap=True)
    t.add_column(style="dim")
    for a, b in rows:
        t.add_row(a, b)
    console.print(Panel(t, title=" Help ", border_style="#ff7f6b", box=ROUNDED, padding=(0, 1)))


def _engine_label(eng, cfg) -> str:
    mid = getattr(eng, "model_id", getattr(cfg, "model_id", "")) or ""
    low = mid.lower()
    if not mid or "dummy" in low:
        return "dummy"
    if "tinyllama" in low:
        return "TinyLlama 1.1B"
    return _pretty_model(mid, 22) or "model"


# ---------- auto web-search trigger (no /web needed) ----------
_NEEDS_SEARCH_RE = __import__("re").compile(
    r"\b(who is|what is|when is|when did|where is|how to|latest|today|news|price|weather|score|release|update|upcoming|current|recent|202[4-9]|2026|compare|vs\.? )",
    __import__("re").I)
_ALWAYS_SEARCH_HINTS = ("search", "google", "look up", "find out", "browse")

def _looks_like_search_prompt(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 4:
        return False
    # explicit "search ..." stays explicit, don't auto-search again
    if t.lower().startswith("/web"):
        return False
    # short factual-ish or time-sensitive => auto search
    low = t.lower()
    if any(h in low for h in _ALWAYS_SEARCH_HINTS):
        return True
    # questions about fresh facts / entities usually benefit
    if _NEEDS_SEARCH_RE.search(t):
        return True
    # heuristic: 0.5B hallucinates dates/people — short "who/what/when" => help it
    if t.endswith("?") and len(t.split()) <= 14 and low.split()[0] in ("who","what","when","where","which","how","is","are","did","does"):
        return True
    return False

def _auto_search_if_needed(console, prompt: str, hist: str, eng, cfg) -> tuple[str, list]:
    """If prompt looks factual/fresh and we're not offline, run web_search quickly.
    Returns (grounded_prompt, results). Falls back to original prompt on any failure.
    Runs inline (already fast) — caller prints status. Timeout is inside websearch._fetch (6s)."""
    if getattr(cfg, "offline", False):
        return prompt, []
    if not _looks_like_search_prompt(prompt):
        return prompt, []
    # Fast-fail: if the network is down, don't eat the full 6s+ search timeout
    # before generation even starts. 1.5s probe instead of a ~12s worst case.
    try:
        if not web_is_online(1.5):
            return prompt, []
    except Exception:
        pass
    try:
        results = web_search(prompt, max_results=3)
    except Exception:
        return prompt, []
    webblock = format_web(results, max_chars=750) if results else ""
    if not webblock:
        return prompt, results
    grounded = prompt + "\n\n" + webblock
    return grounded, results

def _spinner_for_engine(eng, cfg, is_ready_fn, width: int) -> None:
    """Coral spinner replacing the ugly `Loading weights: 0%|...` bar.
    Runs until is_ready_fn() is True. Metered, ghost-aware."""
    import shutil as _sh
    spins = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    label = _engine_label(eng, cfg)
    t0 = time.time()
    i = 0
    w = 60 if not width else width
    # hide cursor while spinning
    try:
        sys.stdout.write("\x1b[?25l")
        sys.stdout.flush()
    except Exception:
        pass
    try:
        while not is_ready_fn():
            try:
                # also exit if background warmup failed
                if getattr(eng, "_warmup_error", None) is not None:
                    break
            except Exception:
                pass
            el = time.time() - t0
            ch = spins[i % len(spins)]
            # coral spin + dim label — fixed width so no jitter
            msg = f"  {CORAL}{ch}{RST}  loading {label}  {DIM}{_mmss(el)}{RST}"
            # pad to overwrite previous line
            pad = max(0, (w - 40))
            sys.stdout.write(f"\r{CORAL}│{RST}{msg}{' ' * 8}  ")
            sys.stdout.flush()
            time.sleep(0.09)
            i += 1
        # clear spinner line, newline so history stays clean
        sys.stdout.write(f"\r{' ' * max(w, 64)}\r")
        sys.stdout.flush()
        if getattr(eng, "_warmup_error", None) is not None:
            e = eng._warmup_error
            sys.stdout.write(f"{DIM}  (model failed to load: {e} — using fallback){RST}\n")
            sys.stdout.flush()
        else:
            el = time.time() - t0
            sys.stdout.write(f"{DIM}  {label} ready · {_mmss(el)}{RST}\n")
            sys.stdout.flush()
    finally:
        try:
            sys.stdout.write("\x1b[?25h")
            sys.stdout.flush()
        except Exception:
            pass


def run_muxe(config_path=None, conversation_id=None, once=None):
    _boost_priority()
    # silence the ugly bar globally for THIS process (before anything imports tqdm/transformers)
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["TQDM_DISABLE"] = "1"
    os.environ["TRANSFORMERS_VERBOSITY"] = "error"
    cfg = load_config(config_path)
    persona = load_persona(cfg)
    # immutable safety guard (persona.txt cannot remove this)
    _safety_suffix = "\n\nSafety: never help with illegal, harmful, privacy-violating requests. Refuse and offer safe alternative."
    if _safety_suffix.strip() not in persona:
        persona = persona.strip() + _safety_suffix
    console = _console()
    name = _app(cfg)

    eng, warns = create_engine(cfg, persona)
    # start loading in background if transformers — banner becomes instant
    _bg_warmup = None
    if hasattr(eng, "warmup_async"):
        try:
            _bg_warmup = eng.warmup_async()  # type: ignore
        except Exception:
            pass
    for w in (warns or [])[-2:]:
        if console is None:
            print(f"[warn] {w}", file=sys.stderr)
        else:
            console.print(Text(f"· {w}", style="dim"))

    conv = None
    if conversation_id:
        conv = load_conversation(conversation_id)
        if conv is None:
            console and console.print(Text(f"Conversation {conversation_id!r} not found — new chat.", style="dim"))
            if console is None:
                print(f"[warn] conversation {conversation_id!r} not found — new chat.", file=sys.stderr)
    if conv is None and not once:
        recent = _recent(1)
        if recent:
            conv = load_conversation(recent[0]["id"])
    if conv is None:
        conv = create_conversation(title="MUXE chat", system_prompt=persona)
    elif not conv.messages or conv.messages[0].role != "system":
        conv.messages.insert(0, Message(role="system", content=persona))

    _banner(console, cfg, eng)

    if console is not None:
        for f in BOOT:
            _draw(f)
            time.sleep(0.04)
        _draw(IDLE[0])

    # interactive: banner is instant — do NOT block here. Spinner shows on first prompt.
    # piped (--once): must block so output contains the answer, not just the banner.
    _is_ready = getattr(eng, "is_ready", lambda: True)
    if once is not None and not _is_ready() and _bg_warmup is not None:
        # piped once waits silently (no coral — stdout must stay plain)
        try:
            thr = getattr(eng, "_warmup_thread", None)
            if thr is not None:
                thr.join(timeout=90)
        except Exception:
            pass
        if not _is_ready() and getattr(eng, "_warmup_error", None) is None:
            try:
                thr.join(timeout=30)
            except Exception:
                pass

    if once is not None and once.strip():
        # if background load still in flight, wait (tty shows coral spinner, piped waits silently)
        _is_ready2 = getattr(eng, "is_ready", lambda: True)
        if not _is_ready2():
            if console is not None:
                _spinner_for_engine(eng, cfg, _is_ready2, console.width or 80)
                if not _is_ready2() and getattr(eng, "_warmup_error", None) is None:
                    thr2 = getattr(eng, "_warmup_thread", None)
                    if thr2 is not None and getattr(thr2, "is_alive", lambda: False)():
                        try: thr2.join(timeout=60)
                        except Exception: pass
                    if not _is_ready2():
                        try: eng.warmup()  # type: ignore
                        except Exception: pass
            else:
                thr2 = getattr(eng, "_warmup_thread", None)
                if thr2 is not None:
                    try: thr2.join(timeout=90)
                    except Exception: pass
                if not _is_ready2() and getattr(eng, "_warmup_error", None) is None:
                    try: eng.warmup()  # type: ignore
                    except Exception: pass
        hist = history_to_text_smart([m.to_dict() for m in conv.messages], max_turns=cfg.max_history_turns)
        # auto web-search grounding (silent, no /web needed)
        grounded_once = once.strip()
        pls_results = []
        try:
            grounded_once, pls_results = _auto_search_if_needed(console, once.strip(), hist, eng, cfg)
            if pls_results and console is None:
                pass  # piped: stay plain
            elif pls_results and console is not None:
                console.print(Text(f"  ↳ auto-searched: {once.strip()[:56]} · {len(pls_results)} hits", style="dim"))
        except Exception:
            grounded_once = once.strip()
        conv.messages.append(Message(role="user", content=once.strip()))
        save_conversation(conv)
        if console is None:
            full, thinking = _stream_plain(grounded_once, hist, eng, cfg)
            conv.messages.append(Message(role="assistant", content=full, thinking=thinking, thoughts_visible=False))
            if conv.title in ("MUXE chat", "New chat"):
                conv.title = _slug(once.strip(), 42).title() or conv.title
            save_conversation(conv)
            sys.exit(0)
        full, thinking, _ = _stream_tty(grounded_once, hist, eng, cfg, console)
        conv.messages.append(Message(role="assistant", content=full, thinking=thinking, thoughts_visible=False))
        if conv.title in ("MUXE chat", "New chat"):
            conv.title = _slug(once.strip(), 42).title() or conv.title
        save_conversation(conv)
        sys.exit(0)

    last_stats = None
    last_thinking = ""
    while True:
        try:
            user = _input_line(console).strip()
        except (EOFError, KeyboardInterrupt):
            save_conversation(conv)
            msg = f"\nSaved -> gully/data/conversations/{conv.id}.json — bye."
            if console is None:
                print(msg)
            else:
                console.print(Text(msg, style="dim"))
            break

        if not user:
            continue

        low = user.lower().strip()
        if low in ("/quit", "/exit", "/q", ":q", "quit()", "exit()"):
            save_conversation(conv)
            msg = f"Saved -> gully/data/conversations/{conv.id}.json — bye."
            if console is None:
                print(msg)
            else:
                console.print(Text(msg, style="dim"))
            break
        if low in ("/help", "?", "/?"):
            _help(console)
            continue
        if low in ("/ghost", "/ghost dance"):
            if console is None:
                print("(mascot dance is terminal-only)")
            else:
                for _ in range(5):
                    _draw(TURBO_B, bright=True)
                    time.sleep(0.12)
                    _draw(TURBO_A)
                    time.sleep(0.12)
                for f in THINK:
                    _draw(f, bright=True)
                    time.sleep(0.1)
                _draw(IDLE[0])
                console.print(Text("  *dance done*", style="#ff7f6b"))
            continue
        if low == "/actions":
            if console is None:
                for a, b in pc_list_actions():
                    print(f"  {a:<28} {b}")
            else:
                t = Table(box=ROUNDED, show_header=False, pad_edge=False, border_style="#ff7f6b")
                t.add_column(style="bold #ff7f6b", no_wrap=True)
                t.add_column(style="dim")
                for a, b in pc_list_actions():
                    t.add_row(a, b)
                console.print(Panel(t, title=" PC control ", border_style="#ff7f6b", box=ROUNDED, padding=(0, 1)))
            continue
        if low.startswith("/do"):
            parts = user.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                console and console.print(Text("Usage: /do open blender — see /actions", style="dim"))
                if console is None:
                    print("Usage: /do <action>")
                continue
            act = pc_try_action(parts[1])
            result = act or "(no matching action — /actions for the list)"
            console and console.print(Text(f"  {result}", style="dim"))
            if console is None:
                print(result)
            continue
        # ---- file ops only (Claude Code style): create folder/file + auto-save FILE: blocks ----
        if console is not None:
            act = pc_try_action(user)
            if act is not None:
                console.print(Text(f"  {act}", style="dim"))
                continue
        if low in ("/online", "/offline"):
            if low == "/offline":
                cfg.offline = True
                msg = "  offline — local model only, no network"
            else:
                cfg.offline = False
                try:
                    alive = web_is_online(2.0)
                except Exception:
                    alive = False
                msg = ("  online — web search enabled"
                       if alive else
                       "  online — but no internet detected right now")
            console and console.print(Text(msg, style="#ff7f6b"))
            if console is None:
                print(msg)
            continue
        if low.startswith("/web"):
            if getattr(cfg, "offline", False):
                msg = "  offline mode — type /online to enable web search"
                console and console.print(Text(msg, style="dim"))
                if console is None:
                    print(msg)
                continue
            parts = user.split(maxsplit=1)
            q = parts[1].strip() if len(parts) > 1 else ""
            if not q:
                console and console.print(Text("Usage: /web <query> — e.g. /web python dict vs list speed", style="dim"))
                if console is None:
                    print("Usage: /web <query>")
                continue
            console and console.print(Text(f"  searching the web: {q}", style="dim"))
            if console is None:
                print(f"[web] {q}")
            try:
                results = web_search(q, max_results=5)
            except Exception as e:
                results = []
            webblock = format_web(results)
            if not results:
                msg = "(no results — offline or blocked; normal chat still works)"
                console and console.print(Text(msg, style="dim"))
                if console is None:
                    print(msg)
                continue
            if console is None:
                for r in results:
                    print(f" - {r['title'][:70]}")
            else:
                for r in results:
                    console.print(Text(f"  · {r['title'][:72]}", style="dim"))
            # grounded generation: feed results as context, answer streams normally
            grounded = (user + "\n\n" + webblock) if webblock else user
            hist = history_to_text_smart([m.to_dict() for m in conv.messages], max_turns=cfg.max_history_turns)
            conv.messages.append(Message(role="user", content=user))
            save_conversation(conv)
            if console is None:
                t0 = time.time()
                full, thinking = _stream_plain(grounded, hist, eng, cfg)
                elapsed = int((time.time() - t0) * 1000)
                ct = estimate_tokens(full)
                last_stats = {"engine": getattr(eng, "name", cfg.engine), "elapsed_ms": elapsed,
                              "tokens": ct, "tok/s": round(ct / (elapsed / 1000), 1) if elapsed else 0,
                              "web": len(results)}
            else:
                full, thinking, elapsed = _stream_tty(grounded, hist, eng, cfg, console)
                ct = estimate_tokens(full)
                last_stats = {"engine": getattr(eng, "name", cfg.engine), "elapsed_ms": elapsed,
                              "tokens": ct, "tok/s": round(ct / (elapsed / 1000), 1) if elapsed else 0,
                              "web": len(results)}
            conv.messages.append(Message(role="assistant", content=full, thinking=thinking, thoughts_visible=False))
            if conv.title in ("MUXE chat", "New chat"):
                conv.title = _slug(q, 42).title() or conv.title
            save_conversation(conv)
            if console is not None:
                console.print()
                _draw(IDLE[0])
            continue
        if low in ("/think", "/thinking"):
            # show the stored thinking trace as plain grey text (no toggle UI)
            found = None
            for m in reversed(conv.messages):
                if m.role == "assistant" and getattr(m, "thinking", None):
                    found = m
                    break
            if not found or not found.thinking:
                print("(no thinking for last reply)")
                continue
            save_conversation(conv)
            if console is None:
                print(found.thinking)
            else:
                console.print(Text(f"  {found.thinking}", style="dim"))
            continue
        if low.startswith("/copy"):
            parts = user.split(maxsplit=1)
            which = parts[1].strip().lower() if len(parts) > 1 else ""
            last = None
            for m in reversed(conv.messages):
                if m.role == "assistant" and (m.content or "").strip():
                    last = m.content
                    break
            if not last:
                msg = "(nothing to copy yet)"
                console and console.print(Text(msg, style="dim"))
                if console is None:
                    print(msg)
                continue
            blocks = _code_blocks(last)
            payload = last
            if which in ("all", "reply", "text"):
                payload = last
            elif blocks:
                if which.isdigit():
                    i = int(which) - 1
                    payload = blocks[i] if 0 <= i < len(blocks) else blocks[-1]
                else:
                    payload = blocks[-1]
            ok = _copy_to_clipboard(payload)
            if ok:
                if payload == last:
                    what = "reply"
                else:
                    what = f"code block ({len(payload.splitlines())} lines)"
                msg = f"  \u29c9 copied {what} to clipboard"
            else:
                msg = "  copy failed (no clipboard access)"
            console and console.print(Text(msg, style="#ff7f6b" if ok else "dim"))
            if console is None:
                print(msg)
            continue
        if low == "/list":
            convs = list_conversations()
            if not convs:
                print("(no conversations yet)")
            elif console is None:
                for c in convs[:10]:
                    print(f" {c['id']}  {c['title'][:28]:28}  {c['updated_at'][:19].replace('T',' ')}  ({c['message_count']} msgs)")
            else:
                t = Table(box=ROUNDED, show_header=True, header_style="bold #ff7f6b",
                          border_style="#ff7f6b", pad_edge=False)
                t.add_column("ID", style="bold yellow", no_wrap=True)
                t.add_column("Title", style="white", max_width=26, overflow="ellipsis")
                t.add_column("Updated", style="dim")
                t.add_column("Msgs", justify="right", style="dim")
                for c in convs[:10]:
                    t.add_row(c["id"], c["title"] or "Untitled",
                              c["updated_at"][:19].replace("T", " "), str(c["message_count"]))
                console.print(Panel(t, box=ROUNDED, border_style="#ff7f6b"))
            continue
        if low.startswith("/load"):
            parts = user.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                console and console.print(Text("Usage: /load <id>  —  see /list", style="dim"))
                if console is None:
                    print("Usage: /load <id>")
                continue
            got = load_conversation(parts[1].strip())
            if not got:
                print(f"Not found: {parts[1].strip()}")
                continue
            conv = got
            if console is None:
                print(f"Loaded {conv.id} — {conv.title} ({len(conv.messages)} msgs)")
            else:
                console.print(Text(f"Loaded {conv.id} — {conv.title}", style="bold #ff7f6b"))
                for m in [x for x in conv.messages if x.role != "system"][-4:]:
                    if m.role == "assistant" and getattr(m, "thinking", None) and getattr(m, "thoughts_visible", False):
                        console.print(Text(f"  {m.thinking}", style="dim"))
                    body = (Markdown(m.content, code_theme="monokai") if "```" in m.content
                            else Text(m.content, style="white" if m.role == "assistant" else "cyan"))
                    console.print(Panel(body, title=f" {m.role} ", box=ROUNDED,
                                        border_style="dim", padding=(0, 1)))
            continue
        if low == "/new":
            save_conversation(conv)
            conv = create_conversation(title="MUXE chat", system_prompt=persona)
            console and console.print(Text(f"New chat {conv.id} — go", style="bold #ff7f6b"))
            if console is None:
                print(f"New chat {conv.id}")
            last_stats = None
            last_thinking = ""
            continue
        if low == "/clear":
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()
            _banner(console, cfg, eng)
            if console is not None:
                for f in BOOT:
                    _draw(f)
                    time.sleep(0.04)
                _draw(IDLE[0])
            continue
        if low == "/stats":
            if last_stats is None:
                print("(no generation yet)")
            elif console is None:
                print(json.dumps(last_stats, indent=2))
            else:
                t = Table(box=ROUNDED, show_header=False, border_style="#ff7f6b", pad_edge=False)
                for k, v in last_stats.items():
                    t.add_row(Text(str(k), style="#ff7f6b"), Text(str(v), style="white"))
                console.print(Panel(t, box=ROUNDED, border_style="dim"))
            continue
        if low in ("/config", "/model", "/info"):
            info = {
                "app": name,
                "engine": getattr(eng, "name", cfg.engine),
                "model": getattr(eng, "model_id", cfg.model_id),
                "gen": asdict(cfg.gen),
                "turns": cfg.max_history_turns,
                "network": "offline" if getattr(cfg, "offline", False) else "online",
                "chat": conv.id,
            }
            if console is None:
                print(json.dumps(info, indent=2))
            else:
                t = Table(box=ROUNDED, show_header=False, border_style="#ff7f6b", pad_edge=False)
                for k, v in info.items():
                    val = json.dumps(v, indent=2) if isinstance(v, dict) else str(v)
                    t.add_row(Text(k, style="#ff7f6b"), Text(val, style="white"))
                console.print(Panel(t, box=ROUNDED, border_style="dim"))
            continue
        if low == "/delete":
            try:
                ans = input(f"Delete {conv.id}? type yes: ").strip().lower()
            except Exception:
                ans = ""
            if ans not in ("yes", "y"):
                print("Cancelled.")
                continue
            delete_conversation(conv.id)
            conv = create_conversation(title="MUXE chat", system_prompt=persona)
            print(f"Deleted. New chat {conv.id}")
            continue

        # ---- generate ----
        # if model still loading, show spinner instead of mysterious silence
        _is_ready3 = getattr(eng, "is_ready", lambda: True)
        if not _is_ready3():
            if console is None:
                thr3 = getattr(eng, "_warmup_thread", None)
                if thr3 is not None:
                    try: thr3.join(timeout=90)
                    except Exception: pass
                if not _is_ready3() and getattr(eng, "_warmup_error", None) is None:
                    try: eng.warmup()  # type: ignore
                    except Exception as e:
                        eng_name = getattr(eng, "name", cfg.engine)
                        if console is None: print(f"[model] {e}")
                        continue
                if not _is_ready3():
                    continue
            else:
                _spinner_for_engine(eng, cfg, _is_ready3, console.width or 80)
                if not _is_ready3() and getattr(eng, "_warmup_error", None) is None:
                    thr3 = getattr(eng, "_warmup_thread", None)
                    if thr3 is not None and getattr(thr3, "is_alive", lambda: False)():
                        try: thr3.join(timeout=60)
                        except Exception: pass
                    if not _is_ready3():
                        try: eng.warmup()  # type: ignore
                        except Exception as e:
                            console.print(Text(f"  model failed: {e}", style="dim"))
                            continue
                if not _is_ready3():
                    console.print(Text(f"  model not ready — try again", style="dim"))
                    continue
        hist = history_to_text_smart([m.to_dict() for m in conv.messages], max_turns=cfg.max_history_turns)
        # auto-search grounding (no /web needed) — only if factual/fresh
        user_grounded = user
        auto_hits = 0
        try:
            user_grounded, _auto_res = _auto_search_if_needed(console, user, hist, eng, cfg)
            auto_hits = len(_auto_res or [])
            if auto_hits and console is not None:
                console.print(Text(f"  ↳ auto-searched: {user[:56]} · {auto_hits} hits", style="dim"))
        except Exception:
            user_grounded = user
        conv.messages.append(Message(role="user", content=user))
        save_conversation(conv)

        if console is None:
            t0 = time.time()
            full, thinking = _stream_plain(user_grounded, hist, eng, cfg)
            elapsed = int((time.time() - t0) * 1000)
            ct = estimate_tokens(full)
            tps = round(ct / (elapsed / 1000), 1) if elapsed else 0
            last_stats = {"engine": getattr(eng, "name", cfg.engine),
                          "elapsed_ms": elapsed, "tokens": ct, "tok/s": tps, "thinking": estimate_tokens(thinking)}
            last_thinking = thinking
        else:
            full, thinking, elapsed = _stream_tty(user_grounded, hist, eng, cfg, console)
            ct = estimate_tokens(full)
            last_stats = {"engine": getattr(eng, "name", cfg.engine), "elapsed_ms": elapsed,
                          "tokens": ct,
                          "tok/s": round(ct / (elapsed / 1000), 1) if elapsed else 0,
                          "thinking": estimate_tokens(thinking)}
            last_thinking = thinking

        conv.messages.append(Message(role="assistant", content=full, thinking=thinking, thoughts_visible=False))
        if conv.title in ("MUXE chat", "New chat"):
            conv.title = _slug(user, 42).title() or conv.title
        save_conversation(conv)
        # Claude Code style: auto-save FILE: blocks
        try:
            if "FILE:" in (full or ""):
                from gully.control import save_generated_files as _s, get_last_folder as _lf  # type: ignore
                base = None
                try: base = _lf()
                except Exception: pass
                saved = _s(full, base)
                if saved:
                    if console is None:
                        print(f"[saved {len(saved)} file(s) -> {base}]")
                    else:
                        console.print(Text(f"  ✓ saved {len(saved)} file(s) -> {base}", style="#ff7f6b"))
                        for p in saved[:8]:
                            console.print(Text(f"    · {p.name}", style="dim"))
        except Exception:
            pass
        if console is not None:
            console.print()
            _draw(IDLE[0])


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="muxe",
        description="MUXE — local LLM terminal. Offline, CPU-only.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='  muxe              interactive\n  muxe "hello"      one-shot\n  muxe --new        new chat\n',
    )
    p.add_argument("--config", default=None)
    p.add_argument("-c", "--conversation", default=None, help="resume id")
    p.add_argument("--once", default=None, help="single prompt then exit")
    p.add_argument("--new", action="store_true", help="force new chat")
    p.add_argument("prompt", nargs="*", help="positional prompt -> one-shot")
    args = p.parse_args(argv)

    once = args.once
    if not once and args.prompt:
        once = " ".join(args.prompt)
    if once and once.strip().lower().startswith("run "):
        once = once.strip()[4:].strip()
        if once.lower().startswith("muxe"):
            once = once[4:].strip()
        if not once:
            once = None
    run_muxe(config_path=args.config,
             conversation_id=None if args.new else args.conversation,
             once=once)


if __name__ == "__main__":
    main()
