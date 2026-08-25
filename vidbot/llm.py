"""Abstracao de LLM. Tres provedores, todos com opcao gratuita.

ollama: local, offline, sem limite. Precisa do modelo baixado.
groq:   nuvem, free tier generoso, ~20x mais rapido que CPU local.
gemini: nuvem, free tier.
"""
from __future__ import annotations

import json
import os
import re

import requests

TIMEOUT = 180


class LLMError(RuntimeError):
    pass


def _extract_json(text: str) -> dict:
    """Modelos pequenos costumam embrulhar o JSON em prosa ou em cercas ```.

    Tentamos o parse direto e, se falhar, recortamos do primeiro { ao ultimo }.
    """
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise LLMError(f"LLM nao retornou JSON valido:\n{text[:500]}")
    return json.loads(text[start : end + 1])


def _ollama(prompt: str, system: str) -> str:
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    r = requests.post(
        f"{host}/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.4},
        },
        timeout=TIMEOUT,
    )
    if r.status_code == 404:
        raise LLMError(
            f"Modelo '{model}' nao encontrado no Ollama. Rode: ollama pull {model}"
        )
    r.raise_for_status()
    return r.json()["message"]["content"]


def _groq(prompt: str, system: str) -> str:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise LLMError("GROQ_API_KEY nao definida no .env")
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.4,
            "response_format": {"type": "json_object"},
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _gemini(prompt: str, system: str) -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise LLMError("GEMINI_API_KEY nao definida no .env")
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key},
        json={
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.4,
                "responseMimeType": "application/json",
            },
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


_PROVIDERS = {"ollama": _ollama, "groq": _groq, "gemini": _gemini}


def ask_json(prompt: str, system: str) -> dict:
    """Chama o provedor configurado e devolve um dict."""
    name = os.getenv("LLM_PROVIDER", "ollama").lower()
    fn = _PROVIDERS.get(name)
    if fn is None:
        raise LLMError(
            f"LLM_PROVIDER='{name}' invalido. Use: {', '.join(_PROVIDERS)}"
        )
    return _extract_json(fn(prompt, system))
