import pytest

from vidbot import bot, config, db, estados as e, perfis, youtube as yt


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


def test_texto_do_corte_traz_id_titulo_e_janela():
    class C:
        id = 9
        titulo = "Um corte"
        inicio_s = 10.0
        fim_s = 50.0
        duracao_s = 40.0
        nota = 85

    texto = bot.montar_texto_corte(C())
    assert "#9" in texto and "Um corte" in texto and "40" in texto


class ServicoFalso:
    def __init__(self, video_id="yt-abc"):
        self.video_id = video_id

    def inserir(self, corpo, caminho):
        return self.video_id


def _corte_aprovado(con):
    jid = db.criar_job(con, "u", "A", "Ep", "@x", 600, "p")
    cid = db.criar_corte(con, jid, 0.0, 40.0, "t", 80)
    db.transicionar_corte(con, cid, e.AGUARDANDO_APROVACAO, e.APROVADO)
    return db.obter_corte(con, cid)


def test_publicar_ou_avisar_sem_servico_nao_publica(con):
    corte = _corte_aprovado(con)
    texto = bot.publicar_ou_avisar(con, corte, perfis.Perfil(nome="p"), {}, None)
    assert "sem token" in texto
    assert db.obter_corte(con, corte.id).estado == e.APROVADO


def test_publicar_ou_avisar_publica_com_sucesso(con):
    corte = _corte_aprovado(con)
    texto = bot.publicar_ou_avisar(con, corte, perfis.Perfil(nome="p"), {"url_original": "u"},
                                   ServicoFalso())
    assert "yt-abc" in texto
    assert db.obter_corte(con, corte.id).estado == e.PUBLICADO


def test_publicar_ou_avisar_sem_quota_avisa_e_mantem_aprovado(con):
    corte = _corte_aprovado(con)
    for i in range(6):
        db.registrar_upload(con, corte.id, f"x{i}", yt.hoje())
    texto = bot.publicar_ou_avisar(con, corte, perfis.Perfil(nome="p"), {"url_original": "u"},
                                   ServicoFalso())
    assert "cota" in texto
    assert db.obter_corte(con, corte.id).estado == e.APROVADO
