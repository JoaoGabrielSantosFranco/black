"""Leitura do .env e diagnostico de credenciais."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

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
    if env is None:
        load_dotenv(RAIZ / ".env")
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


def _tokens_de_canal() -> tuple[bool, str]:
    """Quantos perfis ja tem token OAuth. Sem token o canal nunca publica."""
    from . import perfis as mod_perfis

    perfis_dir, tokens_dir = RAIZ / "perfis", RAIZ / "tokens"
    if not perfis_dir.is_dir():
        return False, f"nenhum perfil em {perfis_dir}"
    todos = mod_perfis.carregar_todos(perfis_dir)
    if not todos:
        return False, f"nenhum perfil em {perfis_dir}"

    faltando = [p.nome for p in todos.values()
                if not p.canal_token or not (tokens_dir / p.canal_token).exists()]
    if faltando:
        return False, ("sem token: " + ", ".join(faltando)
                       + " — rode `main.py autorizar <perfil>`")
    return True, f"{len(todos)} canal(is) prontos para publicar"


def diagnosticar(cfg: Config) -> list[tuple[str, bool, str]]:
    """Linhas (nome, ok, detalhe) para o comando doctor."""
    chave = cfg.groq_api_key if cfg.llm_provider == "groq" else cfg.gemini_api_key
    ffmpeg = shutil.which("ffmpeg")
    livre_gb = shutil.disk_usage(cfg.work_dir.parent).free / 1024**3
    tokens_ok, tokens_detalhe = _tokens_de_canal()
    return [
        ("chave do LLM", bool(chave) or cfg.llm_provider == "ollama", cfg.llm_provider),
        ("ffmpeg", ffmpeg is not None, ffmpeg or "nao encontrado — sudo apt install ffmpeg"),
        ("token do Telegram", bool(cfg.telegram_token), "necessario para `main.py bot`"),
        ("operadores autorizados", bool(cfg.telegram_ids), f"{len(cfg.telegram_ids)} id(s)"),
        ("tokens de canal", tokens_ok, tokens_detalhe),
        ("disco livre", livre_gb >= 3, f"{livre_gb:.1f} GB (minimo 3)"),
    ]
