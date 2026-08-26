import pytest

from vidbot import db, estados as e, perfis, youtube as yt


@pytest.fixture
def con(tmp_path):
    c = db.conectar(tmp_path / "t.sqlite3")
    yield c
    c.close()


@pytest.fixture
def corte(con):
    jid = db.criar_job(con, "u", "A", "Ep", "@x", 600, "p")
    cid = db.criar_corte(con, jid, 10.0, 50.0, "Titulo do corte", 90)
    db.transicionar_corte(con, cid, e.AGUARDANDO_APROVACAO, e.APROVADO)
    return db.obter_corte(con, cid)


class ServicoFalso:
    def __init__(self, video_id="yt-abc"):
        self.video_id = video_id
        self.chamadas = []

    def inserir(self, corpo, caminho):
        self.chamadas.append((corpo, caminho))
        return self.video_id


def _perfil(**kw):
    return perfis.Perfil(nome="p", **kw)


def test_quota_comeca_cheia(con):
    assert yt.uploads_restantes(con, "2026-08-25") == 6


def test_cada_upload_consome_uma_vaga(con, corte):
    db.registrar_upload(con, corte.id, "x", "2026-08-25")
    assert yt.uploads_restantes(con, "2026-08-25") == 5


def test_quota_zera_e_bloqueia(con, corte):
    for i in range(6):
        db.registrar_upload(con, corte.id, f"x{i}", "2026-08-25")
    assert yt.tem_quota(con, "2026-08-25") is False


def test_quota_do_dia_seguinte_esta_livre(con, corte):
    for i in range(6):
        db.registrar_upload(con, corte.id, f"x{i}", "2026-08-25")
    assert yt.tem_quota(con, "2026-08-26") is True


def test_publicar_sem_quota_levanta_e_mantem_aprovado(con, corte):
    for i in range(6):
        db.registrar_upload(con, corte.id, f"x{i}", "2026-08-25")
    with pytest.raises(yt.SemQuota):
        yt.publicar(con, corte, _perfil(), {"url_original": "u"}, ServicoFalso(), "2026-08-25")
    assert db.obter_corte(con, corte.id).estado == e.APROVADO


def test_publicar_marca_como_publicado(con, corte):
    yt.publicar(con, corte, _perfil(), {"url_original": "u"}, ServicoFalso(), "2026-08-25")
    atualizado = db.obter_corte(con, corte.id)
    assert atualizado.estado == e.PUBLICADO and atualizado.youtube_id == "yt-abc"


def test_publicar_recusa_corte_nao_aprovado(con):
    jid = db.criar_job(con, "u", "A", "Ep", "@x", 600, "p")
    cid = db.criar_corte(con, jid, 0.0, 30.0, "t", 50)
    pendente = db.obter_corte(con, cid)
    with pytest.raises(yt.NaoAprovado):
        yt.publicar(con, pendente, _perfil(), {"url_original": "u"}, ServicoFalso(), "2026-08-25")


def test_descricao_credita_a_origem_quando_o_perfil_pede(con, corte):
    texto = yt.montar_descricao(_perfil(creditar_origem=True),
                                {"url_original": "https://y/w?v=A", "canal": "@x"}, corte)
    assert "https://y/w?v=A" in texto and "@x" in texto


def test_descricao_sem_credito_nao_traz_o_link(con, corte):
    texto = yt.montar_descricao(_perfil(creditar_origem=False),
                                {"url_original": "https://y/w?v=A", "canal": "@x"}, corte)
    assert "https://y/w?v=A" not in texto


def test_privacidade_do_perfil_vai_no_corpo(con, corte):
    servico = ServicoFalso()
    yt.publicar(con, corte, _perfil(privacidade="public"), {"url_original": "u"},
                servico, "2026-08-25")
    corpo, _ = servico.chamadas[0]
    assert corpo["status"]["privacyStatus"] == "public"


# ------------------------------------------------- autorizacao OAuth

def test_escopo_e_so_o_de_upload():
    """Menor privilegio: o bot sobe video, nao le nem apaga nada."""
    assert yt.ESCOPOS == ["https://www.googleapis.com/auth/youtube.upload"]


def test_caminho_do_token_sai_do_perfil(tmp_path):
    perfil = perfis.Perfil(nome="p", canal_token="cortes_br.json")
    assert yt.caminho_do_token(perfil, tmp_path) == tmp_path / "cortes_br.json"


def test_perfil_sem_canal_token_nao_tem_caminho(tmp_path):
    assert yt.caminho_do_token(perfis.Perfil(nome="p"), tmp_path) is None


def test_salvar_token_cria_o_diretorio_e_restringe_a_permissao(tmp_path):
    class CredFalsa:
        def to_json(self):
            return '{"token": "abc"}'

    destino = tmp_path / "tokens" / "canal.json"
    yt.salvar_token(CredFalsa(), destino)
    assert destino.read_text() == '{"token": "abc"}'
    # o arquivo carrega refresh_token: ninguem mais na maquina deve ler
    assert oct(destino.stat().st_mode)[-3:] == "600"
