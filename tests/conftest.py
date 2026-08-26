"""Isolamento do ambiente real.

`config.carregar()` sem argumento le o `.env` da raiz do projeto. Sem esta
barreira a suite enxergaria as credenciais reais do desenvolvedor — e o teste
do comando `bot`, que espera recusar por falta de token, subiria um bot de
verdade contra a API do Telegram.
"""
from __future__ import annotations

import pytest

from vidbot import config

VARIAVEIS = (
    "LLM_PROVIDER", "GROQ_API_KEY", "GEMINI_API_KEY",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USER_IDS",
    "VIDBOT_DB", "VIDBOT_WORK",
)


@pytest.fixture(autouse=True)
def ambiente_limpo(tmp_path, monkeypatch):
    """Aponta a raiz para um diretorio vazio e limpa as variaveis herdadas."""
    monkeypatch.setattr(config, "RAIZ", tmp_path)
    for nome in VARIAVEIS:
        monkeypatch.delenv(nome, raising=False)
