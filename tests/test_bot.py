import pytest

from vidbot import bot, config, db, estados as e


@pytest.fixture
def con(tmp_path):
    c = db.conectar(tmp_path / "t.sqlite3")
    yield c
    c.close()


def _cfg(ids="7"):
    return config.carregar({"TELEGRAM_ALLOWED_USER_IDS": ids})


def _corte(con):
    jid = db.criar_job(con, "u", "A", "Ep", "@x", 600, "p")
    return db.criar_corte(con, jid, 0.0, 40.0, "t", 80)


def test_operador_listado_e_autorizado():
    assert bot.autorizado(7, _cfg()) is True


def test_estranho_e_recusado():
    assert bot.autorizado(999, _cfg()) is False


def test_sem_lista_ninguem_entra():
    assert bot.autorizado(7, _cfg(ids="")) is False


def test_callback_e_lido():
    assert bot.ler_callback("aprovar:12") == ("aprovar", 12)


def test_callback_malformado_devolve_none():
    assert bot.ler_callback("lixo") is None
    assert bot.ler_callback("aprovar:abc") is None
    assert bot.ler_callback("") is None


def test_aprovar_leva_o_corte_para_aprovado(con):
    cid = _corte(con)
    assert bot.decidir_corte(con, "aprovar", cid) == e.APROVADO


def test_descartar_leva_para_rejeitado(con):
    cid = _corte(con)
    assert bot.decidir_corte(con, "descartar", cid) == e.REJEITADO


def test_refazer_leva_para_refazer(con):
    cid = _corte(con)
    assert bot.decidir_corte(con, "refazer", cid) == e.REFAZER


def test_acao_desconhecida_nao_muda_nada(con):
    cid = _corte(con)
    with pytest.raises(ValueError):
        bot.decidir_corte(con, "publicar_agora", cid)
    assert db.obter_corte(con, cid).estado == e.AGUARDANDO_APROVACAO


def test_decidir_duas_vezes_nao_reaplica(con):
    cid = _corte(con)
    bot.decidir_corte(con, "aprovar", cid)
    with pytest.raises(bot.JaDecidido):
        bot.decidir_corte(con, "descartar", cid)
