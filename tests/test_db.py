import pytest

from vidbot import db, estados as e


@pytest.fixture
def con(tmp_path):
    c = db.conectar(tmp_path / "t.sqlite3")
    yield c
    c.close()


def _job(con):
    return db.criar_job(con, url="https://y/w?v=A", video_id="A", titulo="Ep 1",
                        canal_origem="@x", duracao_s=6000, perfil="cortes_br")


def test_job_nasce_em_novo(con):
    j = db.obter_job(con, _job(con))
    assert j.estado == e.NOVO and j.video_id == "A"


def test_transicao_valida_muda_o_estado(con):
    jid = _job(con)
    assert db.transicionar_job(con, jid, e.NOVO, e.LEGENDA_OBTIDA) is True
    assert db.obter_job(con, jid).estado == e.LEGENDA_OBTIDA


def test_transicao_proibida_e_recusada(con):
    jid = _job(con)
    with pytest.raises(db.TransicaoInvalida):
        db.transicionar_job(con, jid, e.NOVO, e.RENDERIZADO)


def test_transicao_com_estado_de_origem_errado_nao_aplica(con):
    """Protege contra dois processos transicionando o mesmo job."""
    jid = _job(con)
    db.transicionar_job(con, jid, e.NOVO, e.LEGENDA_OBTIDA)
    assert db.transicionar_job(con, jid, e.NOVO, e.LEGENDA_OBTIDA) is False


def test_proximo_job_respeita_ordem_de_criacao(con):
    primeiro = _job(con)
    _job(con)
    assert db.proximo_job(con, [e.NOVO]).id == primeiro


def test_proximo_job_ignora_estados_nao_pedidos(con):
    _job(con)
    assert db.proximo_job(con, [e.RENDERIZADO]) is None


def test_erro_fica_gravado_no_job(con):
    jid = _job(con)
    db.transicionar_job(con, jid, e.NOVO, e.ERRO, erro="yt-dlp caiu")
    assert db.obter_job(con, jid).erro == "yt-dlp caiu"


def test_cortes_saem_na_ordem_do_tempo(con):
    jid = _job(con)
    db.criar_corte(con, jid, 300.0, 340.0, "B", 70)
    db.criar_corte(con, jid, 100.0, 160.0, "A", 90)
    assert [c.titulo for c in db.cortes_do_job(con, jid)] == ["A", "B"]


def test_corte_nasce_aguardando_aprovacao(con):
    jid = _job(con)
    cid = db.criar_corte(con, jid, 10.0, 40.0, "T", 80)
    assert db.obter_corte(con, cid).estado == e.AGUARDANDO_APROVACAO


def test_contador_de_upload_e_por_dia(con):
    jid = _job(con)
    cid = db.criar_corte(con, jid, 10.0, 40.0, "T", 80)
    db.registrar_upload(con, cid, "yt123", "2026-08-25")
    assert db.uploads_no_dia(con, "2026-08-25") == 1
    assert db.uploads_no_dia(con, "2026-08-26") == 0


def test_listar_jobs_retorna_lista_vazia_se_nenhum(con):
    jobs = db.listar_jobs(con)
    assert jobs == []


def test_listar_jobs_retorna_em_ordem_decrescente(con):
    j1 = _job(con)
    j2 = _job(con)
    j3 = _job(con)
    jobs = db.listar_jobs(con)
    assert [j.id for j in jobs] == [j3, j2, j1]


def test_listar_jobs_retorna_dataclass_job(con):
    _job(con)
    jobs = db.listar_jobs(con)
    assert len(jobs) == 1
    j = jobs[0]
    assert isinstance(j, db.Job)
    assert j.id == 1
    assert j.video_id == "A"
    assert j.titulo == "Ep 1"
    assert j.perfil == "cortes_br"


def test_listar_jobs_respeita_limite(con):
    for _ in range(5):
        _job(con)
    assert len(db.listar_jobs(con, limite=3)) == 3
    assert len(db.listar_jobs(con, limite=10)) == 5
