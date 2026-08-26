import pytest

from vidbot import config, llm


def _cfg(**e):
    base = {"LLM_PROVIDER": "groq", "GROQ_API_KEY": "g", "GEMINI_API_KEY": "m"}
    base.update(e)
    return config.carregar(base)


def test_usa_o_provedor_configurado(monkeypatch):
    monkeypatch.setattr(llm, "_CHAMADAS", {"groq": lambda *_: '{"ok": 1}'})
    assert llm.perguntar_json("p", "s", _cfg()) == {"ok": 1}


def test_cai_para_o_proximo_provedor_quando_o_primeiro_falha(monkeypatch):
    def quebra(*_):
        raise RuntimeError("429 free tier")

    monkeypatch.setattr(llm, "_CHAMADAS", {
        "groq": quebra,
        "gemini": lambda *_: '{"ok": 2}',
    })
    assert llm.perguntar_json("p", "s", _cfg()) == {"ok": 2}


def test_json_sujo_ainda_e_aproveitado(monkeypatch):
    monkeypatch.setattr(llm, "_CHAMADAS", {"groq": lambda *_: 'claro:\n```json\n{"ok": 3}\n```'})
    assert llm.perguntar_json("p", "s", _cfg()) == {"ok": 3}


def test_todos_falhando_levanta_sem_provedor(monkeypatch):
    def quebra(*_):
        raise RuntimeError("caiu")

    monkeypatch.setattr(llm, "_CHAMADAS", {"groq": quebra, "gemini": quebra})
    with pytest.raises(llm.SemProvedor):
        llm.perguntar_json("p", "s", _cfg())


def test_provedor_sem_chave_e_pulado(monkeypatch):
    monkeypatch.setattr(llm, "_CHAMADAS", {
        "groq": lambda *_: (_ for _ in ()).throw(AssertionError("nao deveria chamar")),
        "gemini": lambda *_: '{"ok": 4}',
    })
    assert llm.perguntar_json("p", "s", _cfg(GROQ_API_KEY="")) == {"ok": 4}
