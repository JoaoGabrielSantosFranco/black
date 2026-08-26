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


class ServicoQuebrado:
    def inserir(self, corpo, caminho):
        raise RuntimeError("HttpError 500: backend error")


def test_falha_de_upload_vira_erro_upload_e_nao_escapa(con):
    """Sem isso o corte fica presdo em APROVADO: retocar cai em JaDecidido
    e nada nunca marca ERRO_UPLOAD."""
    corte = _corte_aprovado(con)
    texto = bot.publicar_ou_avisar(con, corte, perfis.Perfil(nome="p"), {"url_original": "u"},
                                   ServicoQuebrado())
    assert "falhou" in texto and "backend error" in texto
    assert db.obter_corte(con, corte.id).estado == e.ERRO_UPLOAD


def test_erro_de_upload_fica_gravado_no_corte(con):
    corte = _corte_aprovado(con)
    bot.publicar_ou_avisar(con, corte, perfis.Perfil(nome="p"), {"url_original": "u"},
                           ServicoQuebrado())
    assert "backend error" in db.obter_corte(con, corte.id).erro


# ------------------------------------------------- formatacao das mensagens

def test_tempo_vira_hms_em_video_longo():
    assert bot.tempo_hms(5022) == "01:23:42"


def test_tempo_curto_omite_a_hora():
    assert bot.tempo_hms(47) == "00:47"
    assert bot.tempo_hms(125) == "02:05"


class _Corte:
    id = 9
    titulo = "ELE ACHOU QUE IA DAR CERTO"
    descricao = "Leon tenta uma estrategia inesperada e o resultado e absurdo"
    inicio_s = 5022.0
    fim_s = 5069.0
    duracao_s = 47.0
    nota = 92


class _Job:
    titulo = "LEON E NILCE JOGAM POR 2 HORAS"
    canal_origem = "@leon"


def test_texto_do_corte_mostra_a_descricao_da_ia():
    texto = bot.montar_texto_corte(_Corte())
    assert "estrategia inesperada" in texto


def test_texto_do_corte_usa_janela_legivel():
    texto = bot.montar_texto_corte(_Corte())
    assert "01:23:42" in texto and "01:24:29" in texto and "47s" in texto


def test_texto_do_corte_mostra_a_origem_quando_ha_job():
    texto = bot.montar_texto_corte(_Corte(), _Job())
    assert "@leon" in texto and "LEON E NILCE" in texto


def test_texto_do_corte_escapa_html_do_modelo():
    """Titulo vem do LLM: um < solto quebraria o parse_mode do Telegram."""
    class Hostil(_Corte):
        titulo = "olha o <b> disso & aquilo"
        descricao = ""

    texto = bot.montar_texto_corte(Hostil())
    assert "&lt;b&gt;" in texto and "&amp;" in texto


def test_texto_do_corte_sem_descricao_nao_deixa_buraco():
    class SemDescricao(_Corte):
        descricao = ""

    texto = bot.montar_texto_corte(SemDescricao())
    assert "\n\n\n" not in texto and "ELE ACHOU" in texto


def test_ajuda_lista_os_comandos_que_existem():
    ajuda = bot.montar_ajuda()
    for comando in ("/cortes", "/status", "/canais", "/fila", "/ajuda"):
        assert comando in ajuda


def test_status_resume_a_fabrica(con):
    from vidbot import canais

    canais.cadastrar(con, "@leon", "cortes_br")
    jid = db.criar_job(con, "u", "A", "Ep", "@x", 600, "cortes_br")
    cid = db.criar_corte(con, jid, 0, 40, "t", 90)
    db.definir_caminho_corte(con, cid, "/w/1.mp4")
    texto = bot.montar_status(con)
    assert "1" in texto and "canal" in texto.lower()
    assert "aprova" in texto.lower() and "cota" in texto.lower()


def test_status_com_tudo_vazio_nao_quebra(con):
    assert bot.montar_status(con)


def test_texto_dos_canais_lista_os_monitorados(con):
    from vidbot import canais

    canais.cadastrar(con, "@leon", "cortes_br")
    canais.cadastrar(con, "@nilce", "cortes_br")
    texto = bot.montar_texto_canais(con)
    assert "@leon" in texto and "@nilce" in texto


def test_texto_dos_canais_vazio_ensina_a_cadastrar(con):
    texto = bot.montar_texto_canais(con)
    assert "canais add" in texto


# ------------------------------------------------- refazer de verdade

def _corte_renderizado(con):
    jid = db.criar_job(con, "u", "A", "Ep", "@x", 600, "p")
    cid = db.criar_corte(con, jid, 0.0, 40.0, "t", 80)
    db.definir_caminho_corte(con, cid, "/w/1.mp4")
    db.transicionar_job(con, jid, e.NOVO, e.LEGENDA_OBTIDA)
    db.transicionar_job(con, jid, e.LEGENDA_OBTIDA, e.SEGMENTADO)
    db.transicionar_job(con, jid, e.SEGMENTADO, e.RENDERIZADO)
    return jid, cid


def test_refazer_devolve_o_corte_para_a_fila_de_render(con):
    """O botao so vale se algo de fato re-renderiza: limpa o arquivo e
    volta o job para SEGMENTADO."""
    jid, cid = _corte_renderizado(con)
    bot.decidir_corte(con, "refazer", cid)
    corte = db.obter_corte(con, cid)
    assert corte.caminho is None
    assert corte.estado == e.AGUARDANDO_APROVACAO
    assert db.obter_job(con, jid).estado == e.SEGMENTADO


def test_corte_a_refazer_some_da_lista_ate_renderizar(con):
    _jid, cid = _corte_renderizado(con)
    bot.decidir_corte(con, "refazer", cid)
    assert db.listar_cortes_pendentes(con) == []


def test_refazer_nao_mexe_no_job_que_nao_esta_renderizado(con):
    jid = db.criar_job(con, "u", "A", "Ep", "@x", 600, "p")
    cid = db.criar_corte(con, jid, 0.0, 40.0, "t", 80)
    bot.decidir_corte(con, "refazer", cid)
    assert db.obter_job(con, jid).estado == e.NOVO
