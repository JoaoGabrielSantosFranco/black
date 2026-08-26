import pytest

from vidbot import validate as v


def test_extrai_json_puro():
    assert v.extrair_json('{"a": 1}') == {"a": 1}


def test_extrai_json_dentro_de_cerca():
    assert v.extrair_json('bla\n```json\n{"a": 1}\n```\nfim') == {"a": 1}


def test_extrai_json_com_prosa_em_volta():
    assert v.extrair_json('Claro! {"a": 1} espero ter ajudado') == {"a": 1}


def test_sem_json_levanta():
    with pytest.raises(v.SaidaInvalida):
        v.extrair_json("nao tem json aqui")


def test_numero_fora_da_faixa_e_grampeado():
    assert v.numero(999, 0, 100, 50) == 100
    assert v.numero(-5, 0, 100, 50) == 0


def test_numero_invalido_usa_o_padrao():
    assert v.numero("abc", 0, 100, 50) == 50
    assert v.numero(None, 0, 100, 50) == 50


def test_escolha_fora_da_whitelist_usa_o_padrao():
    assert v.escolha("magica", {"centro", "rosto"}, "centro") == "centro"
    assert v.escolha("ROSTO", {"centro", "rosto"}, "centro") == "rosto"


def test_cor_aceita_com_e_sem_cerquilha():
    assert v.cor_hex("FFD400", "#FFFFFF") == "#FFD400"
    assert v.cor_hex("#ffd400", "#FFFFFF") == "#FFD400"


def test_cor_invalida_usa_o_padrao():
    assert v.cor_hex("amarelo", "#FFFFFF") == "#FFFFFF"


def test_texto_e_truncado_e_limpo():
    assert v.texto("  oi  ", limite=10) == "oi"
    assert len(v.texto("x" * 500, limite=10)) == 10
