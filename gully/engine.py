"""
MUXE — engine abstraction.
- Dummy fast, transformers with ChatML, GGUF fallback. All CPU, low RAM.
- Now with synthetic thinking trace and true token-by-token streaming.
"""
from __future__ import annotations

import os, random, re, time
from dataclasses import dataclass
from typing import Iterator
from .config import AppConfig

@dataclass
class GenStats:
    engine: str
    model_id: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    elapsed_ms: int
    tokens_per_sec: float

def estimate_tokens(text: str) -> int:
    return max(1, len(text)//4) if text else 0

# ---------------- thinking (synthetic, safe) ----------------

def thinking_trace(prompt: str, hist: str = "", persona: str = "") -> str:
    """Deterministic, safe internal reasoning — streamed token-by-token like Claude."""
    p = (prompt or "").strip().replace("\n", " ")[:120]
    if not p:
        p = "empty prompt"
    hist_turns = 0
    if hist:
        try:
            hist_turns = hist.count("User:")
        except Exception:
            hist_turns = 0
    # keep it grounded, harmless, shows planning
    parts = [
        f'Need to answer: "{p}".',
        f"Context: {hist_turns} prior turns, persona={'yes' if persona else 'default'}.",
        "Plan: 1) understand intent 2) recall history 3) outline key points 4) keep tone friendly/helpful 5) check safety.",
        "Safety: ensure no disallowed/harmful content, no privacy violation, be concise and accurate.",
        "Ready to produce final answer token-by-token.",
    ]
    return " ".join(parts)

def _chunk_text(text: str, n: int = 4) -> Iterator[str]:
    if not text:
        return
    # keep words mostly intact but split long words
    # yield n-char slices to simulate tokens
    i = 0
    L = len(text)
    while i < L:
        yield text[i:i+n]
        i += n

def thinking_token_stream(prompt: str, hist: str = "", persona: str = "", chunk: int = 4, delay: float = 0.018) -> Iterator[str]:
    trace = thinking_trace(prompt, hist, persona)
    for tok in _chunk_text(trace, chunk):
        yield tok
        if delay:
            time.sleep(delay + random.random()*0.006)

_DUMMY_RESPONSES = [
    "Arre {name} is here — bindaas! Dummy mode chal raha ({tok} tok context) — full app works, drop a GGUF later to go big brain.",
    "Mast sawal! I'm running dummy — {tok} tok, {turns} turns memory. Real model (Qwen 0.5B) is way smarter, same code.",
    "Yo {name} bol! MUXE live — {eng} · {model}. Try a follow-up, I remember context.",
]

def _dummy_reply(user_text: str, persona: str, hist: str, app_name: str, cfg: AppConfig) -> str:
    t = user_text.strip().lower()
    name = app_name
    if any(w in t for w in ("hello","hi","hey","namaste","yo")):
        return f"Heyyy! {name} here — ekdum ready. What's the scene today?"
    if any(w in t for w in ("who are you","what are you","tum kaun")):
        return f"Main {name} — your local chatbot. Offline, CPU-only. No cloud. {cfg.gen.n_ctx} ctx, {cfg.max_history_turns} turns memory."
    if any(w in t for w in ("how are you","kaisa","kya haal")):
        return "Ekdam mast! RAM bhi khush. Tum batao — kya chal raha?"
    if "help" in t:
        return "I chat, remember context, save locally, stream. Try /help, /list, /config. No net needed after setup."
    return random.choice(_DUMMY_RESPONSES).format(name=name, tok=cfg.gen.n_ctx, turns=cfg.max_history_turns, eng="dummy", model="local") + f"\n\nYou said: \"{user_text.strip()[:120]}\""

class DummyEngine:
    name = "dummy"
    def __init__(self, cfg: AppConfig, persona: str):
        self.cfg=cfg; self.persona=persona; self.model_id="dummy (no model)"
        self._tok=object(); self._model=object()  # type: ignore
    def is_ready(self) -> bool: return True
    def warmup_async(self): return None
    def warmup(self): pass
    def generate(self, prompt: str, hist: str = "", **kw) -> tuple[str, GenStats]:
        t0=time.time()
        text=_dummy_reply(prompt,self.persona,hist,self.cfg.app_name,self.cfg)
        max_tok=int(kw.get("max_new_tokens", self.cfg.gen.max_new_tokens))
        if len(text) > max_tok*4:
            text=text[:max_tok*4].rsplit(" ",1)[0]+"…"
        elapsed=int((time.time()-t0)*1000)+random.randint(40,120)
        pt=estimate_tokens(hist+prompt); ct=estimate_tokens(text)
        return text, GenStats(self.name,self.model_id,pt,ct,pt+ct,elapsed, ct/(elapsed/1000) if elapsed else 0)
    def stream(self, prompt: str, hist: str = "", **kw) -> Iterator[str]:
        text,_=self.generate(prompt,hist,**kw)
        # true token-by-token like ChatGPT: 4-char chunks
        for tok in _chunk_text(text, 4):
            yield tok
            time.sleep(0.016 + random.random()*0.008)
    def stream_thinking(self, prompt: str, hist: str = "", **kw) -> Iterator[str]:
        yield from thinking_token_stream(prompt, hist, self.persona, chunk=4, delay=0.016)
    def unload(self): pass

class TransformersEngine:
    name="transformers"
    def __init__(self, cfg: AppConfig, persona: str):
        self.cfg=cfg; self.persona=persona
        self.model_id=cfg.model_id or "Qwen/Qwen2-0.5B-Instruct"
        self._tok=None; self._model=None
        self._warmup_thread=None  # type: ignore
        self._warmup_error=None  # type: ignore
        self._warmup_started_at=None  # type: ignore

    def is_ready(self) -> bool:
        return self._tok is not None and self._model is not None

    def warmup_async(self):
        """Start loading in background — banner shows instantly."""
        if self.is_ready():
            return self._warmup_thread
        thr=getattr(self, "_warmup_thread", None)
        if thr is not None and getattr(thr, "is_alive", lambda: False)():
            return thr
        import threading
        self._warmup_error=None
        self._warmup_started_at=time.time()
        def _run():
            try: self.warmup()
            except Exception as e:
                self._warmup_error=e
        t=threading.Thread(target=_run, daemon=True, name="muxe-warmup")
        self._warmup_thread=t; t.start()
        return t

    def wait_ready(self, timeout: float | None = None) -> bool:
        thr=getattr(self, "_warmup_thread", None)
        if thr is not None:
            thr.join(timeout)
        return self.is_ready()

    def warmup(self):
        import os, torch
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        os.environ["HF_HUB_DISABLE_PROGRESS_BARS"]="1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"]="1"
        os.environ["TQDM_DISABLE"]="1"
        os.environ["TRANSFORMERS_VERBOSITY"]="error"
        # silence transformers + huggingface_hub + accelerate progress bars (that ugly "Loading weights: 0%" bar)
        try:
            from transformers.utils import logging as _tflog
            _tflog.disable_progress_bar()
            _tflog.set_verbosity_error()
        except Exception: pass
        try:
            from huggingface_hub.utils import disable_progress_bars as _dis2
            _dis2()
        except Exception: pass
        # kill the "Loading weights: 0%|..." tqdm from accelerate — make every tqdm silent
        try:
            import tqdm as _tqdm_mod  # type: ignore
            _orig = getattr(_tqdm_mod, "tqdm", None)
            if _orig is not None:
                def _silent_tqdm(*a, **kw):  # type: ignore
                    kw["disable"] = True
                    return _orig(*a, **kw)
                _tqdm_mod.tqdm = _silent_tqdm  # type: ignore
            try:
                import tqdm.auto as _tqa  # type: ignore
                if getattr(_tqa, "tqdm", None) is not None:
                    _tqa.tqdm = _tqdm_mod.tqdm  # type: ignore
            except Exception:
                pass
        except Exception:
            pass
        try:
            threads = int(getattr(self.cfg.gen, "threads", 0) or 0)
            if threads > 0:
                torch.set_num_threads(threads)
                try: torch.set_num_interop_threads(1)
                except Exception: pass
                try: torch.set_float32_matmul_precision('high')
                except Exception: pass
        except Exception: pass
        from transformers import AutoTokenizer, AutoModelForCausalLM
        # local-first fast path: skip all HF hub HTTP checks when files are cached
        local = False
        try:
            from huggingface_hub import try_to_load_from_cache
            local = (try_to_load_from_cache(self.model_id, "config.json") is not None)
        except Exception:
            local = False
        kwargs = dict(trust_remote_code=False, low_cpu_mem_usage=True, dtype="auto")
        if local:
            kwargs["local_files_only"] = True
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        try:
            tok = AutoTokenizer.from_pretrained(self.model_id, **kwargs)
            # force silence: some transformers versions ignore env and still pass a tqdm callback
            try:
                import transformers.modeling_utils as _mu  # type: ignore
                _orig_tqdm2 = getattr(_mu, "tqdm", None)
            except Exception:
                _orig_tqdm2 = None
            model = AutoModelForCausalLM.from_pretrained(self.model_id, **kwargs)
        except Exception:
            # cache miss on some file — fall back to online load (downloads once)
            kwargs.pop("local_files_only", None)
            tok = AutoTokenizer.from_pretrained(self.model_id, trust_remote_code=False)
            model = AutoModelForCausalLM.from_pretrained(self.model_id, trust_remote_code=False, low_cpu_mem_usage=True, dtype="auto")
        try: model.eval()
        except Exception: pass
        self._tok=tok; self._model=model

    def _build_prompt(self, hist: str, user: str) -> str:
        if self._tok is not None and getattr(self._tok, "chat_template", None):
            try:
                msgs=[]
                if self.persona.strip():
                    msgs.append({"role":"system","content": self.persona.strip()})
                for line in hist.split("\n"):
                    if line.startswith("User: "): msgs.append({"role":"user","content": line[6:]})
                    elif line.startswith("Assistant: "): msgs.append({"role":"assistant","content": line[11:]})
                msgs.append({"role":"user","content": user})
                return self._tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)  # type: ignore
            except Exception:
                pass
        parts=[]
        if self.persona.strip():
            parts.append(f"<|im_start|>system\n{self.persona.strip()}<|im_end|>")
        if hist:
            for line in hist.split("\n"):
                if line.startswith("User: "): parts.append(f"<|im_start|>user\n{line[6:]}<|im_end|>")
                elif line.startswith("Assistant: "): parts.append(f"<|im_start|>assistant\n{line[11:]}<|im_end|>")
        parts.append(f"<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n")
        return "\n".join(parts)

    def generate(self, prompt: str, hist: str = "", **kw) -> tuple[str, GenStats]:
        if not self.is_ready():
            thr=getattr(self, "_warmup_thread", None)
            if thr is not None and getattr(thr,"is_alive",lambda:False)():
                self.wait_ready()
            if not self.is_ready():
                self.warmup()
        import torch
        t0=time.time()
        full=self._build_prompt(hist, prompt)
        inputs=self._tok(full, return_tensors="pt", truncation=True, max_length=self.cfg.gen.n_ctx)  # type: ignore
        max_new=int(kw.get("max_new_tokens", self.cfg.gen.max_new_tokens))
        temp=float(kw.get("temperature", self.cfg.gen.temperature))
        do_sample=temp>0.05
        with torch.no_grad():  # type: ignore
            out=self._model.generate(**inputs, max_new_tokens=max_new, do_sample=do_sample,  # type: ignore
                temperature=temp if do_sample else None,
                top_p=float(kw.get("top_p", self.cfg.gen.top_p)) if do_sample else None,
                top_k=int(kw.get("top_k", self.cfg.gen.top_k)) if do_sample else None,
                repetition_penalty=float(kw.get("repeat_penalty", self.cfg.gen.repeat_penalty)),
                pad_token_id=self._tok.eos_token_id)  # type: ignore
        text=self._tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()  # type: ignore
        text=re.sub(r"<\|im_start\|>.*?\|im_end\|>", "", text, flags=re.S).strip()
        text=re.sub(r"^(User:|Assistant:|system|user|assistant)\s*:?", "", text, flags=re.I|re.M).strip()
        elapsed=int((time.time()-t0)*1000)
        pt=int(inputs["input_ids"].shape[1])  # type: ignore
        ct=estimate_tokens(text)
        return text, GenStats(self.name,self.model_id,pt,ct,pt+ct,elapsed, ct/(elapsed/1000) if elapsed else 0)

    def stream(self, prompt: str, hist: str = "", **kw) -> Iterator[str]:
        try:
            from transformers import TextIteratorStreamer
            import threading
            if not self.is_ready():
                thr=getattr(self, "_warmup_thread", None)
                if thr is not None and getattr(thr,"is_alive",lambda:False)():
                    self.wait_ready()
                if not self.is_ready():
                    self.warmup()
            full=self._build_prompt(hist,prompt)
            inputs=self._tok(full, return_tensors="pt", truncation=True, max_length=self.cfg.gen.n_ctx)  # type: ignore
            streamer=TextIteratorStreamer(self._tok, skip_special_tokens=True, skip_prompt=True)  # type: ignore
            import torch
            temp=float(kw.get("temperature",self.cfg.gen.temperature))
            do_sample=temp>0.05
            gen_kwargs=dict(
                **inputs, max_new_tokens=int(kw.get("max_new_tokens", self.cfg.gen.max_new_tokens)),
                do_sample=do_sample,
                pad_token_id=self._tok.eos_token_id, streamer=streamer)  # type: ignore
            if do_sample:
                gen_kwargs["temperature"]=temp
                gen_kwargs["top_p"]=float(kw.get("top_p",self.cfg.gen.top_p))
                gen_kwargs["top_k"]=int(kw.get("top_k",self.cfg.gen.top_k))
                gen_kwargs["repetition_penalty"]=float(kw.get("repeat_penalty",self.cfg.gen.repeat_penalty))
            else:
                gen_kwargs["repetition_penalty"]=float(kw.get("repeat_penalty",self.cfg.gen.repeat_penalty))
            t=threading.Thread(target=self._model.generate, kwargs=gen_kwargs)  # type: ignore
            t.daemon=True
            t.start()
            for chunk in streamer: yield chunk
            t.join(); return
        except Exception:
            text,_=self.generate(prompt,hist,**kw)
            for tok in _chunk_text(text, 4):
                yield tok; time.sleep(0.014)

    def stream_thinking(self, prompt: str, hist: str = "", **kw) -> Iterator[str]:
        yield from thinking_token_stream(prompt, hist, self.persona, chunk=4, delay=0.016)

    def unload(self):
        try: del self._model; del self._tok  # type: ignore
        except: pass

class LlamaCppEngine:
    name="llama_cpp"
    def __init__(self, cfg, persona): self.cfg=cfg; self.persona=persona; self.model_path=self._resolve(cfg); self.model_id=self.model_path or cfg.model_id or "(no GGUF)"; self._llm=None; self._warmup_thread=None; self._warmup_error=None  # type: ignore
    def is_ready(self) -> bool: return self._llm is not None
    def warmup_async(self):
        if self.is_ready(): return self._warmup_thread
        thr=getattr(self,"_warmup_thread",None)
        if thr is not None and getattr(thr,"is_alive",lambda:False)(): return thr
        import threading
        self._warmup_error=None
        def _run():
            try: self.warmup()
            except Exception as e: self._warmup_error=e
        t=threading.Thread(target=_run, daemon=True, name="muxe-warmup-llama"); self._warmup_thread=t; t.start(); return t
    @staticmethod
    def _resolve(cfg):
        from pathlib import Path
        cands=[]
        if cfg.model_file: cands.append(Path(cfg.model_file))
        if cfg.model_id and cfg.model_id.endswith(".gguf"): cands.append(Path(cfg.model_id))
        for d in [Path("gully/models"), Path.cwd()/ "gully"/"models"]:
            if d.is_dir():
                cands+=list(d.glob("*.gguf"))+list(d.glob("*.GGUF"))
        for c in cands:
            if c.exists(): return str(c.resolve())
        return ""
    def warmup(self):
        if not self.model_path: raise RuntimeError("No GGUF in gully/models/")
        from llama_cpp import Llama
        threads=int(getattr(self.cfg.gen,"threads",0) or 0) or max(1,(os.cpu_count() or 4)//2)
        self._llm=Llama(model_path=self.model_path, n_ctx=self.cfg.gen.n_ctx, n_threads=threads, verbose=False)  # type: ignore
    def _prompt(self,h,u): return (f"<|im_start|>system\n{self.persona}<|im_end|>\n" if self.persona else "") + (h+"\n" if h else "") + f"<|im_start|>user\n{u}<|im_end|>\n<|im_start|>assistant\n"
    def generate(self,p,h="",**kw):
        if not self.is_ready():
            thr=getattr(self,"_warmup_thread",None)
            if thr is not None and getattr(thr,"is_alive",lambda:False)():
                try: thr.join(timeout=12)
                except Exception: pass
            if not self.is_ready(): self.warmup()
        t0=time.time(); out=self._llm(self._prompt(h,p), max_tokens=int(kw.get("max_new_tokens",self.cfg.gen.max_new_tokens)), temperature=float(kw.get("temperature",self.cfg.gen.temperature)), top_p=float(kw.get("top_p",self.cfg.gen.top_p)), top_k=int(kw.get("top_k",self.cfg.gen.top_k)), repeat_penalty=float(kw.get("repeat_penalty",self.cfg.gen.repeat_penalty)), stop=["<|im_start|>","User:","System:"])  # type: ignore
        text=out["choices"][0]["text"].strip()  # type: ignore
        elapsed=int((time.time()-t0)*1000); return text, GenStats(self.name,self.model_id, estimate_tokens(h+p), estimate_tokens(text), estimate_tokens(h+p+text), elapsed, estimate_tokens(text)/(elapsed/1000) if elapsed else 0)
    def stream(self,p,h="",**kw):
        if not self.is_ready():
            thr=getattr(self,"_warmup_thread",None)
            if thr is not None and getattr(thr,"is_alive",lambda:False)():
                try: thr.join(timeout=12)
                except Exception: pass
            if not self.is_ready(): self.warmup()
        for ch in self._llm.create_completion(self._prompt(h,p), max_tokens=int(kw.get("max_new_tokens",self.cfg.gen.max_new_tokens)), temperature=float(kw.get("temperature",self.cfg.gen.temperature)), top_p=float(kw.get("top_p",self.cfg.gen.top_p)), top_k=int(kw.get("top_k",self.cfg.gen.top_k)), repeat_penalty=float(kw.get("repeat_penalty",self.cfg.gen.repeat_penalty)), stop=["<|im_start|>","User:"], stream=True):  # type: ignore
            yield ch["choices"][0]["text"]  # type: ignore
    def stream_thinking(self,p,h="",**kw):
        yield from thinking_token_stream(p,h,self.persona, chunk=4, delay=0.016)
    def unload(self): self._llm=None

class CTransformersEngine:
    name="ctransformers"
    def __init__(self,cfg,persona): self.cfg=cfg; self.persona=persona; self.model_path=LlamaCppEngine._resolve(cfg); self.model_id=self.model_path or "(no GGUF)"; self._llm=None; self._warmup_thread=None; self._warmup_error=None  # type: ignore
    def is_ready(self) -> bool: return self._llm is not None
    def warmup_async(self):
        if self.is_ready(): return self._warmup_thread
        thr=getattr(self,"_warmup_thread",None)
        if thr is not None and getattr(thr,"is_alive",lambda:False)(): return thr
        import threading
        self._warmup_error=None
        def _run():
            try: self.warmup()
            except Exception as e: self._warmup_error=e
        t=threading.Thread(target=_run, daemon=True, name="muxe-warmup-ctr"); self._warmup_thread=t; t.start(); return t
    def _qwen_prompt(self, hist: str, user: str) -> str:
        parts=[]
        if self.persona.strip():
            parts.append(f"<|im_start|>system\n{self.persona.strip()}<|im_end|>")
        if hist:
            for line in hist.split("\n"):
                if line.startswith("User: "): parts.append(f"<|im_start|>user\n{line[6:]}<|im_end|>")
                elif line.startswith("Assistant: "): parts.append(f"<|im_start|>assistant\n{line[11:]}<|im_end|>")
        parts.append(f"<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n")
        return "\n".join(parts)
    def warmup(self):
        if not self.model_path: raise RuntimeError("No GGUF")
        from ctransformers import AutoModelForCausalLM
        threads = int(getattr(self.cfg.gen, "threads", 4) or 4)
        # auto-detect qwen vs tinyllama/qwen name
        mt=(self.cfg.model_type or "").strip().lower()
        if not mt:
            low=(self.model_path or "").lower()
            if "tinyllama" in low: mt="llama"
            elif "qwen2" in low or "qwen" in low: mt="qwen2"
            else: mt="qwen2"
        try:
            self._llm=AutoModelForCausalLM.from_pretrained(self.model_path, model_type=mt, max_new_tokens=self.cfg.gen.max_new_tokens, context_length=self.cfg.gen.n_ctx, threads=threads, gpu_layers=0)  # type: ignore
        except Exception as e:
            # fallback: tinyllama name can be `llama` or auto
            if "qwen2" in str(e).lower() and mt=="qwen2":
                self._llm=AutoModelForCausalLM.from_pretrained(self.model_path, model_type="llama", max_new_tokens=self.cfg.gen.max_new_tokens, context_length=self.cfg.gen.n_ctx, threads=threads, gpu_layers=0)  # type: ignore
            else:
                raise
    def generate(self,p,h="",**kw):
        if not self.is_ready():
            thr=getattr(self,"_warmup_thread",None)
            if thr is not None and getattr(thr,"is_alive",lambda:False)():
                try: thr.join(timeout=12)
                except Exception: pass
            if not self.is_ready(): self.warmup()
        t0=time.time(); full=self._qwen_prompt(h,p)
        text=self._llm(full, max_new_tokens=int(kw.get("max_new_tokens",self.cfg.gen.max_new_tokens)), temperature=float(kw.get("temperature",self.cfg.gen.temperature)), top_p=float(kw.get("top_p",self.cfg.gen.top_p)), top_k=int(kw.get("top_k",self.cfg.gen.top_k)), repetition_penalty=float(kw.get("repeat_penalty",self.cfg.gen.repeat_penalty)), stop=["<|im_start|>","<|im_end|>","User:"]).strip()  # type: ignore
        elapsed=int((time.time()-t0)*1000); return text, GenStats(self.name,self.model_id, estimate_tokens(full), estimate_tokens(text), estimate_tokens(full+text), elapsed, estimate_tokens(text)/(elapsed/1000) if elapsed else 0)
    def stream(self,p,h="",**kw):
        # REAL token-by-token: each token yields the instant the model forms it
        if not self.is_ready():
            thr=getattr(self,"_warmup_thread",None)
            if thr is not None and getattr(thr,"is_alive",lambda:False)():
                try: thr.join(timeout=12)
                except Exception: pass
            if not self.is_ready(): self.warmup()
        try:
            for ch in self._llm.create_completion(self._qwen_prompt(h,p), max_tokens=int(kw.get("max_new_tokens",self.cfg.gen.max_new_tokens)), temperature=float(kw.get("temperature",self.cfg.gen.temperature)), top_p=float(kw.get("top_p",self.cfg.gen.top_p)), top_k=int(kw.get("top_k",self.cfg.gen.top_k)), repeat_penalty=float(kw.get("repeat_penalty",self.cfg.gen.repeat_penalty)), stop=["<|im_start|>","<|im_end|>","User:"], stream=True):  # type: ignore
                yield ch["choices"][0]["text"]  # type: ignore
        except Exception:
            text,_=self.generate(p,h,**kw)
            for tok in _chunk_text(text, 4):
                yield tok
    def stream_thinking(self,p,h="",**kw):
        yield from thinking_token_stream(p,h,self.persona, chunk=4, delay=0.016)
    def unload(self): self._llm=None

_ENGINE_MAP={"dummy":DummyEngine,"transformers":TransformersEngine,"llama_cpp":LlamaCppEngine,"llama-cpp":LlamaCppEngine,"ctransformers":CTransformersEngine}

def create_engine(cfg: AppConfig, persona: str):
    name=(cfg.engine or "auto").strip().lower()
    if name in _ENGINE_MAP:
        eng=_ENGINE_MAP[name](cfg,persona)  # type: ignore
        try:
            if name=="dummy": eng.warmup()
            return eng, []
        except Exception as e: return DummyEngine(cfg,persona), [f"[{name}] {e} — dummy"]
    if name=="auto":
        warns=[]
        for cand in ("llama_cpp","ctransformers","transformers"):
            eng=_ENGINE_MAP[cand](cfg,persona)  # type: ignore
            if cand in ("llama_cpp","ctransformers") and not getattr(eng,"model_path",""): warns.append(f"[{cand}] no GGUF — skip"); continue
            if cand=="transformers" and not cfg.model_id: warns.append("[transformers] no model_id — skip"); continue
            warns.append(f"[auto] {cand}"); return eng, warns
        return DummyEngine(cfg,persona), warns+["[auto] dummy"]
    return DummyEngine(cfg,persona), [f"unknown {cfg.engine} — dummy"]

def history_to_text(messages: list, max_turns: int = 10) -> str:
    # filter system but keep thinking traces out of history
    filt=[m for m in messages if getattr(m,"role", m.get("role") if isinstance(m,dict) else "")!="system"]  # type: ignore
    # also ignore thinking pseudo-role
    filt=[m for m in filt if getattr(m,"role", m.get("role") if isinstance(m,dict) else "") not in ("thinking",)]
    win=filt[-(max_turns*2):]
    out=[]
    for m in win:
        r=getattr(m,"role", m.get("role") if isinstance(m,dict) else "user")  # type: ignore
        c=getattr(m,"content", m.get("content") if isinstance(m,dict) else "")  # type: ignore
        if r=="user": out.append(f"User: {c}")
        elif r=="assistant": out.append(f"Assistant: {c}")
    return "\n".join(out)

def history_to_text_smart(messages: list, max_turns: int = 10, summary_budget: int = 420) -> str:
    """Smarter memory: last max_turns verbatim + summarized older turns.
    No extra RAM — just string compression. Keeps persona context without blowing n_ctx."""
    filt=[m for m in messages if getattr(m,"role", m.get("role") if isinstance(m,dict) else "")!="system"]  # type: ignore
    filt=[m for m in filt if getattr(m,"role", m.get("role") if isinstance(m,dict) else "") not in ("thinking",)]
    if not filt:
        return ""
    # verbatim window
    verbs=filt[-(max_turns*2):]
    older=filt[:-(max_turns*2)] if len(filt) > max_turns*2 else []
    summary=""
    if older:
        # compress older into one line per turn, last 8 only
        lines=[]
        for m in older[-8:]:
            r=getattr(m,"role", m.get("role") if isinstance(m,dict) else "user")  # type: ignore
            c=(getattr(m,"content", m.get("content") if isinstance(m,dict) else "") or "").strip().replace("\n"," ")  # type: ignore
            c=c[:90]
            if not c:
                continue
            # keep role hint short
            tag="U" if r=="user" else "A"
            lines.append(f"{tag}:{c}")
        txt=" | ".join(lines)
        if len(txt) > summary_budget:
            txt=txt[:summary_budget].rsplit(" ",1)[0]+"…"
        if txt:
            summary=f"[Earlier summary: {txt}]"
    verb_text=[]
    for m in verbs:
        r=getattr(m,"role", m.get("role") if isinstance(m,dict) else "user")  # type: ignore
        c=getattr(m,"content", m.get("content") if isinstance(m,dict) else "")  # type: ignore
        if r=="user": verb_text.append(f"User: {c}")
        elif r=="assistant": verb_text.append(f"Assistant: {c}")
    parts=[]
    if summary: parts.append(summary)
    parts.extend(verb_text)
    return "\n".join(parts)
