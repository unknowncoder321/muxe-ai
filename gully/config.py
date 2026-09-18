"""
GULLY — configuration.
Everything is tunable from gully/config.yaml or environment variables.
Designed for 6 GB RAM: conservative defaults, no large-model assumptions.
"""
from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field, asdict
from typing import Any

try:
    import yaml  # optional
except Exception:
    yaml = None  # type: ignore


PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
CONVERSATIONS_DIR = PROJECT_ROOT / "data" / "conversations"
MODELS_DIR = PROJECT_ROOT / "models"
PERSONA_FILE = PROJECT_ROOT / "persona.txt"


@dataclass
class GenParams:
    # Safe for weak CPU — small context, modest tokens
    max_new_tokens: int = 256
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 40
    repeat_penalty: float = 1.1
    # context window — intentionally small
    n_ctx: int = 1024
    # threads: 0 = auto (half logical), else explicit
    threads: int = 0


@dataclass
class AppConfig:
    app_name: str = "GULLY"
    host: str = "127.0.0.1"
    port: int = 8766  # separate from Lantern Isles (8765)
    # engine: "auto" | "dummy" | "ctransformers" | "llama_cpp" | "transformers"
    # "auto" tries real backends in order, falls back to dummy
    engine: str = "auto"
    # Hugging Face model id or local path for real backends (GGUF for llama_cpp)
    model_id: str = ""  # e.g. "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF" or local .gguf
    model_file: str = ""  # e.g. "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
    model_type: str = ""  # for ctransformers, e.g. "llama"
    # generation
    gen: GenParams = field(default_factory=GenParams)
    # max conversation turns kept as context (sliding window)
    max_history_turns: int = 10
    # persona file path override
    persona_file: str = str(PERSONA_FILE)
    # offline: if true, never attempt network fetches
    offline: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "AppConfig":
        gen = d.get("gen") or {}
        # tolerate flat keys too
        cfg = AppConfig()
        for k in ("app_name", "host", "port", "engine", "model_id", "model_file", "model_type", "max_history_turns", "persona_file", "offline"):
            if k in d:
                setattr(cfg, k, d[k])
        if isinstance(gen, dict):
            for k, v in gen.items():
                if hasattr(cfg.gen, k):
                    setattr(cfg.gen, k, v)
        return cfg


DEFAULT_YAML_PATH = PROJECT_ROOT / "config.yaml"


def _env_overrides(cfg: AppConfig) -> AppConfig:
    m = {
        "GULLY_APP_NAME": "app_name",
        "GULLY_HOST": "host",
        "GULLY_PORT": "port",
        "GULLY_ENGINE": "engine",
        "GULLY_MODEL_ID": "model_id",
        "GULLY_MODEL_FILE": "model_file",
        "GULLY_MODEL_TYPE": "model_type",
        "GULLY_PERSONA_FILE": "persona_file",
        "GULLY_OFFLINE": "offline",
    }
    for env, attr in m.items():
        v = os.environ.get(env)
        if v is None or v == "":
            continue
        cur = getattr(cfg, attr)
        if isinstance(cur, bool):
            setattr(cfg, attr, v.lower() in ("1", "true", "yes", "on"))
        elif isinstance(cur, int):
            try:
                setattr(cfg, attr, int(v))
            except ValueError:
                pass
        else:
            setattr(cfg, attr, v)
    # gen overrides: GULLY_TEMPERATURE, GULLY_MAX_NEW_TOKENS, etc.
    gen_map = {
        "GULLY_TEMPERATURE": ("temperature", float),
        "GULLY_TOP_P": ("top_p", float),
        "GULLY_TOP_K": ("top_k", int),
        "GULLY_MAX_NEW_TOKENS": ("max_new_tokens", int),
        "GULLY_N_CTX": ("n_ctx", int),
        "GULLY_THREADS": ("threads", int),
        "GULLY_REPEAT_PENALTY": ("repeat_penalty", float),
        "GULLY_MAX_HISTORY_TURNS": None,  # handled above
    }
    for env, spec in gen_map.items():
        if spec is None:
            continue
        v = os.environ.get(env)
        if not v:
            continue
        attr, cast = spec
        try:
            setattr(cfg.gen, attr, cast(v))
        except ValueError:
            pass
    return cfg


def load_config(yaml_path: pathlib.Path | str | None = None) -> AppConfig:
    """
    Load config with precedence: defaults < YAML < env vars.
    Missing YAML is not an error.
    """
    cfg = AppConfig()
    path = pathlib.Path(yaml_path) if yaml_path else DEFAULT_YAML_PATH
    if yaml is not None and path.exists():
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(raw, dict):
                cfg = AppConfig.from_dict(raw)
        except Exception as e:
            print(f"[gully] Warning: failed to read {path}: {e} — using defaults.")
    elif path.exists() and yaml is None:
        print(f"[gully] PyYAML not installed, ignoring {path}. Using defaults + env.")

    cfg = _env_overrides(cfg)
    # ensure dirs
    try:
        CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return cfg


def save_config(cfg: AppConfig, yaml_path: pathlib.Path | str | None = None) -> None:
    path = pathlib.Path(yaml_path) if yaml_path else DEFAULT_YAML_PATH
    if yaml is None:
        raise RuntimeError("PyYAML is required to save config.yaml (pip install pyyaml)")
    d = cfg.to_dict()
    path.write_text(yaml.safe_dump(d, sort_keys=False, allow_unicode=True), encoding="utf-8")


def load_persona(cfg: AppConfig) -> str:
    p = pathlib.Path(cfg.persona_file)
    if not p.exists():
        p = PERSONA_FILE
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        text = "You are GULLY, a friendly local chatbot."
    # strip comment lines so humans can keep notes in persona.txt without
    # paying for them in every single prompt
    text = "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith("#")
    ).strip()
    # template the app name
    return text.replace("{{APP_NAME}}", cfg.app_name)
