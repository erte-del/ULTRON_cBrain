"""Ollama (the local brain): which models are installed, and which one to chat with.

Only ever talks to config.OLLAMA_URL, which config.py insists is on this machine.
"""

import json
import logging
import urllib.request

import config

log = logging.getLogger("ultron.ollama")


def installed() -> list[str] | None:
    """Names of the models Ollama has, or None when it isn't running."""
    try:
        with urllib.request.urlopen(config.OLLAMA_URL + "/api/tags", timeout=3) as r:
            data = json.load(r)
        return sorted(m["name"] for m in data.get("models", []))
    except (OSError, ValueError, KeyError):
        return None


def _base(name: str) -> str:
    """"ultron-qwen3-8b:latest" -> "ultron-qwen3-8b" (Ollama adds :latest to untagged names)."""
    return name.removesuffix(":latest")


def has(models: list[str], wanted: str) -> bool:
    return _base(wanted) in {_base(m) for m in models}


def chat_models(models: list[str]) -> list[str]:
    """The ones to offer for chat: made by scripts/make_ollama_model.py (ultron-*) or named in
    .env. A plain model like qwen3:8b has a 4k window, which cuts Ultron's prompt off."""
    return [m for m in models if m.startswith("ultron-") or (config.OLLAMA_MODEL and _base(m) == _base(config.OLLAMA_MODEL))]


def default_model(models: list[str]) -> str | None:
    """JARVIS_OLLAMA_MODEL if installed, else the first model made by scripts/make_ollama_model.py
    (named ultron-*, with the 32k context Ultron's prompt needs), else None."""
    if config.OLLAMA_MODEL and has(models, config.OLLAMA_MODEL):
        return config.OLLAMA_MODEL
    return next((m for m in models if m.startswith("ultron-")), None)


def warm(model: str, keep_alive: str = "30m") -> bool:
    """Load the model into memory now, so the first message doesn't wait for it (a 14B model
    takes several seconds to load). Asks Ollama for an empty generation; False if it can't."""
    body = json.dumps({"model": model, "prompt": "", "keep_alive": keep_alive}).encode()
    req = urllib.request.Request(config.OLLAMA_URL + "/api/generate", body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            r.read()
        return True
    except (OSError, ValueError):
        log.info("Could not warm up %s", model)
        return False
