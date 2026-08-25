"""Leitura do .env e diagnostico de credenciais."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

PROVEDORES = {"groq", "gemini", "ollama"}
RAIZ = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    llm_provider: str
    groq_api_key: str
    gemini_api_key: str
    telegram_token: str
    telegram_ids: list[int]
    db_path: Path
    work_dir: Path

    _ENV = {
        "groq_api_key": "GROQ_API_KEY",
        "gemini_api_key": "GEMINI_API_KEY",
        "telegram_token": "TELEGRAM_BOT_TOKEN",
    }

    def faltando(self, *campos: str) -> list[str]:
        return [self._ENV[c] for c in campos if not getattr(self, c, "")]


def _ler_ids(bruto: str) -> list[int]:
    ids = []
    for parte in bruto.split(","):
        parte = parte.strip()
        if parte.isdigit():
            ids.append(int(parte))
    return ids


def carregar(env: dict | None = None) -> Config:
    e = dict(os.environ if env is None else env)
    provider = e.get("LLM_PROVIDER", "groq").strip().lower()
    if provider not in PROVEDORES:
        provider = "groq"
    return Config(
        llm_provider=provider,
        groq_api_key=e.get("GROQ_API_KEY", "").strip(),
        gemini_api_key=e.get("GEMINI_API_KEY", "").strip(),
        telegram_token=e.get("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_ids=_ler_ids(e.get("TELEGRAM_ALLOWED_USER_IDS", "")),
        db_path=Path(e.get("VIDBOT_DB", RAIZ / "vidbot.sqlite3")),
        work_dir=Path(e.get("VIDBOT_WORK", RAIZ / "work")),
    )


def diagnosticar(cfg: Config) -> list[tuple[str, bool, str]]:
    """Linhas (nome, ok, detalhe) para o comando doctor."""
    chave = cfg.groq_api_key if cfg.llm_provider == "groq" else cfg.gemini_api_key
    ffmpeg = shutil.which("ffmpeg")
    livre_gb = shutil.disk_usage(cfg.work_dir.parent).free / 1024**3
    return [
        ("chave do LLM", bool(chave) or cfg.llm_provider == "ollama", cfg.llm_provider),
        ("ffmpeg", ffmpeg is not None, ffmpeg or "nao encontrado — sudo apt install ffmpeg"),
        ("token do Telegram", bool(cfg.telegram_token), "opcional ate a Tarefa 11"),
        ("operadores autorizados", bool(cfg.telegram_ids), f"{len(cfg.telegram_ids)} id(s)"),
        ("disco livre", livre_gb >= 3, f"{livre_gb:.1f} GB (minimo 3)"),
    ]
