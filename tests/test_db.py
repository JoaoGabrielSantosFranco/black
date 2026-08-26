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


def _corte_renderizado(con, job_id, inicio=0.0, fim=30.0, titulo="t", nota=90):
    cid = db.criar_corte(con, job_id, inicio, fim, titulo, nota)
    db.definir_caminho_corte(con, cid, f"/w/{cid}.mp4")
    return cid


def test_listar_cortes_pendentes_ignora_outros_estados(con):
    jid = _job(con)
    aprovado = _corte_renderizado(con, jid, 0.0, 30.0, "aprovado", 90)
    db.transicionar_corte(con, aprovado, e.AGUARDANDO_APROVACAO, e.APROVADO)
    pendente = _corte_renderizado(con, jid, 40.0, 70.0, "pendente", 80)
    assert [c.id for c in db.listar_cortes_pendentes(con)] == [pendente]


def test_listar_cortes_pendentes_atravessa_jobs_mais_recente_primeiro(con):
    j1 = _job(con)
    j2 = _job(con)
    c1 = _corte_renderizado(con, j1, 0.0, 30.0, "um", 90)
    c2 = _corte_renderizado(con, j2, 0.0, 30.0, "dois", 90)
    assert [c.id for c in db.listar_cortes_pendentes(con)] == [c2, c1]


def test_listar_cortes_pendentes_respeita_limite(con):
    jid = _job(con)
    for i in range(5):
        cid = db.criar_corte(con, jid, i * 10.0, i * 10.0 + 5.0, f"c{i}", 80)
        db.definir_caminho_corte(con, cid, f"/w/{cid}.mp4")
    assert len(db.listar_cortes_pendentes(con, limite=3)) == 3


def test_listar_cortes_aprovados_traz_os_que_esperam_upload(con):
    jid = _job(con)
    aprovado = _corte_renderizado(con, jid, 0.0, 30.0, "aprovado", 90)
    db.transicionar_corte(con, aprovado, e.AGUARDANDO_APROVACAO, e.APROVADO)
    _corte_renderizado(con, jid, 40.0, 70.0, "pendente", 80)
    assert [c.id for c in db.listar_cortes_aprovados(con)] == [aprovado]


def test_listar_cortes_aprovados_ordena_do_mais_antigo(con):
    """Fila de upload: quem esperou mais sobe primeiro."""
    jid = _job(con)
    ids = []
    for i in range(3):
        cid = _corte_renderizado(con, jid, i * 10.0, i * 10.0 + 5.0, f"c{i}", 80)
        db.transicionar_corte(con, cid, e.AGUARDANDO_APROVACAO, e.APROVADO)
        ids.append(cid)
    assert [c.id for c in db.listar_cortes_aprovados(con)] == ids


def test_listar_cortes_pendentes_ignora_corte_ainda_nao_renderizado(con):
    """Corte nasce em AGUARDANDO_APROVACAO no `selecionar`, antes de existir
    arquivo. Publicar isso subiria um caminho vazio para o YouTube."""
    jid = _job(con)
    db.criar_corte(con, jid, 0.0, 30.0, "sem arquivo", 90)
    renderizado = db.criar_corte(con, jid, 40.0, 70.0, "com arquivo", 80)
    db.definir_caminho_corte(con, renderizado, "/w/2.mp4")
    assert [c.id for c in db.listar_cortes_pendentes(con)] == [renderizado]


def test_corte_guarda_a_descricao(con):
    jid = _job(con)
    cid = db.criar_corte(con, jid, 0.0, 40.0, "t", 90, descricao="uma descricao")
    assert db.obter_corte(con, cid).descricao == "uma descricao"


def test_banco_antigo_sem_a_coluna_e_migrado(tmp_path):
    """Quem ja rodava antes do campo existir nao pode perder o banco."""
    import sqlite3

    caminho = tmp_path / "antigo.sqlite3"
    antigo = sqlite3.connect(caminho)
    antigo.executescript("""
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL,
            video_id TEXT NOT NULL, titulo TEXT NOT NULL DEFAULT '',
            canal_origem TEXT NOT NULL DEFAULT '', duracao_s INTEGER NOT NULL DEFAULT 0,
            perfil TEXT NOT NULL, estado TEXT NOT NULL, erro TEXT,
            criado_em TEXT NOT NULL DEFAULT (datetime('now')),
            atualizado_em TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE cortes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL,
            inicio_s REAL NOT NULL, fim_s REAL NOT NULL,
            titulo TEXT NOT NULL DEFAULT '', nota INTEGER NOT NULL DEFAULT 0,
            estado TEXT NOT NULL, caminho TEXT, youtube_id TEXT, erro TEXT);
        INSERT INTO jobs (url, video_id, perfil, estado) VALUES ('u','A','p','NOVO');
        INSERT INTO cortes (job_id, inicio_s, fim_s, titulo, nota, estado)
            VALUES (1, 0, 40, 'antigo', 90, 'AGUARDANDO_APROVACAO');
    """)
    antigo.commit()
    antigo.close()

    con = db.conectar(caminho)
    corte = db.obter_corte(con, 1)
    assert corte.titulo == "antigo" and corte.descricao == ""
    con.close()
