from pathlib import Path
from vidbot import config


def _env(**extra):
    base = {"LLM_PROVIDER": "groq", "GROQ_API_KEY": "k", "TELEGRAM_ALLOWED_USER_IDS": "7, 9"}
    base.update(extra)
    return base


def test_carrega_ids_do_telegram_como_inteiros():
    cfg = config.carregar(_env())
    assert cfg.telegram_ids == [7, 9]


def test_ids_vazios_viram_lista_vazia():
    cfg = config.carregar(_env(TELEGRAM_ALLOWED_USER_IDS=""))
    assert cfg.telegram_ids == []


def test_id_nao_numerico_e_ignorado():
    cfg = config.carregar(_env(TELEGRAM_ALLOWED_USER_IDS="7, abc, 9"))
    assert cfg.telegram_ids == [7, 9]


def test_faltando_aponta_campo_vazio():
    cfg = config.carregar(_env(GROQ_API_KEY=""))
    assert cfg.faltando("groq_api_key") == ["GROQ_API_KEY"]


def test_faltando_nao_aponta_campo_preenchido():
    cfg = config.carregar(_env())
    assert cfg.faltando("groq_api_key") == []


def test_provider_desconhecido_vira_groq():
    cfg = config.carregar(_env(LLM_PROVIDER="magica"))
    assert cfg.llm_provider == "groq"


def test_diagnostico_reprova_sem_chave():
    cfg = config.carregar(_env(GROQ_API_KEY=""))
    linhas = dict((nome, ok) for nome, ok, _ in config.diagnosticar(cfg))
    assert linhas["chave do LLM"] is False
