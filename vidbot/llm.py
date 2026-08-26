"""LLM com fallback entre provedores. Free tier cai; a esteira nao pode parar."""
from __future__ import annotations

import logging

import requests

from .validate import extrair_json

log = logging.getLogger(__name__)
TIMEOUT = 120


class SemProvedor(RuntimeError):
    """Todos os provedores falharam."""


def _groq(prompt: str, sistema: str, cfg) -> str:
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {cfg.groq_api_key}"},
        json={"model": "llama-3.3-70b-versatile",
              "messages": [{"role": "system", "content": sistema},
                           {"role": "user", "content": prompt}],
              "temperature": 0.4,
              "response_format": {"type": "json_object"}},
        timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _gemini(prompt: str, sistema: str, cfg) -> str:
    r = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.0-flash:generateContent",
        headers={"x-goog-api-key": cfg.gemini_api_key},
        json={"system_instruction": {"parts": [{"text": sistema}]},
              "contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": 0.4,
                                   "responseMimeType": "application/json"}},
        timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _ollama(prompt: str, sistema: str, _cfg) -> str:
    r = requests.post(
        "http://localhost:11434/api/chat",
        json={"model": "llama3.2:3b", "stream": False, "format": "json",
              "messages": [{"role": "system", "content": sistema},
                           {"role": "user", "content": prompt}]},
        timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["message"]["content"]


_CHAMADAS = {"groq": _groq, "gemini": _gemini, "ollama": _ollama}
_CHAVE = {"groq": "groq_api_key", "gemini": "gemini_api_key"}


def _tem_chave(nome: str, cfg) -> bool:
    campo = _CHAVE.get(nome)
    return True if campo is None else bool(getattr(cfg, campo, ""))


def perguntar_json(prompt: str, sistema: str, cfg,
                   provedores: list[str] | None = None) -> dict:
    """Tenta o provedor configurado e depois os demais. Devolve dict."""
    ordem = provedores or [cfg.llm_provider] + [
        p for p in _CHAMADAS if p != cfg.llm_provider
    ]
    problemas = []
    for nome in ordem:
        chamada = _CHAMADAS.get(nome)
        if chamada is None or not _tem_chave(nome, cfg):
            continue
        try:
            return extrair_json(chamada(prompt, sistema, cfg))
        except Exception as erro:  # noqa: BLE001 - queremos tentar o proximo
            log.warning("provedor %s falhou: %s", nome, erro)
            problemas.append(f"{nome}: {erro}")
    raise SemProvedor("; ".join(problemas) or "nenhum provedor com chave")
