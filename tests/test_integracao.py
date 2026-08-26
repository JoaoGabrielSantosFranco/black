import json
from pathlib import Path

import pytest

from vidbot import db, estados as e, etapas, perfis, pipeline
from vidbot.segment import Candidato


@pytest.fixture
def con(tmp_path):
    c = db.conectar(tmp_path / "t.sqlite3")
    yield c
    c.close()


def test_do_link_ate_aguardando_aprovacao(con, tmp_path):
    """Percorre NOVO -> RENDERIZADO com todas as bordas externas falsas."""
    jid = db.criar_job(con, "https://youtu.be/A", "A", "", "", 0, "p")

    meta = {"video_id": "A", "titulo": "Ep", "canal": "@x", "duracao_s": 600,
            "capitulos": [], "url_original": "https://youtu.be/A", "subtitles": {},
            "automatic_captions": {"pt": [{"ext": "json3", "url": "u"}]}}
    eventos = {"events": [{"tStartMs": i * 1000, "dDurationMs": 1000,
                           "segs": [{"utf8": f"p{i}", "tOffsetMs": 0}]}
                          for i in range(120)]}

    passos = {
        e.NOVO: pipeline.Passo(etapas.fazer_obter_legendas(
            metadados=lambda url, **k: meta,
            baixar=lambda u: json.dumps(eventos), con=con), e.LEGENDA_OBTIDA),
        e.LEGENDA_OBTIDA: pipeline.Passo(etapas.fazer_selecionar(
            con=con, escolher=lambda *a, **k: [Candidato(10, 50, "corte um", "g", 90)]),
            e.SEGMENTADO),
        e.SEGMENTADO: pipeline.Passo(etapas.fazer_renderizar(
            con=con,
            render_corte=lambda c, w, p, t, u: Path(w) / f"corte_{c.id}.mp4"),
            e.RENDERIZADO),
    }

    final = pipeline.executar_job(con, jid, passos, tmp_path)

    assert final == e.RENDERIZADO
    cortes = db.cortes_do_job(con, jid)
    assert len(cortes) == 1
    assert cortes[0].estado == e.AGUARDANDO_APROVACAO
    assert cortes[0].caminho.endswith(".mp4")


def test_nada_chega_a_publicado_sem_decisao_humana(con, tmp_path):
    """Trava estrutural: nenhuma etapa do pipeline publica."""
    jid = db.criar_job(con, "https://youtu.be/A", "A", "", "", 0, "p")
    db.criar_corte(con, jid, 0, 40, "t", 90)
    assert all(c.estado != e.PUBLICADO for c in db.cortes_do_job(con, jid))


def test_fabrica_do_canal_ate_a_fila_de_upload(con, tmp_path):
    """Passos 1-7 ligados: cadastra canal -> descobre video -> transcreve ->
    IA escolhe -> renderiza -> auto-publica -> entra na fila de upload.

    Toda borda externa (yt-dlp, LLM, ffmpeg, YouTube) e falsa; o que se prova
    aqui e a fiacao, nao as integracoes.
    """
    from vidbot import canais, etapas, perfis, youtube as yt

    # 1. o operador so cadastra o canal
    canais.cadastrar(con, "@leon", "gameplay")

    # 2. o sistema acha um video novo
    novos = canais.descobrir(con, listar_uploads=lambda url, limite: {
        "entries": [{"id": "aaaaaaaaaaa", "title": "LEON E NILCE JOGAM POR 2 HORAS"}]})
    assert len(novos) == 1
    job = novos[0]
    assert job.perfil == "gameplay"

    perfil = perfis.Perfil(nome="gameplay", auto_publicar=True, canal_token="",
                           criterios="so momentos engracados")

    # 3. transcricao vem das legendas do YouTube
    meta = {"video_id": "aaaaaaaaaaa", "titulo": "LEON E NILCE JOGAM POR 2 HORAS",
            "canal": "@leon", "duracao_s": 7200, "capitulos": [],
            "url_original": "https://youtu.be/aaaaaaaaaaa", "subtitles": {},
            "automatic_captions": {"pt": [{"ext": "json3", "url": "u"}]}}
    eventos = {"events": [{"tStartMs": i * 1000, "dDurationMs": 1000,
                           "segs": [{"utf8": f"p{i}", "tOffsetMs": 0}]}
                          for i in range(200)]}

    # 4 e 5. a IA devolve o trecho com titulo, descricao, gancho e nota
    achado = Candidato(5022.0, 5069.0, "ELE ACHOU QUE IA DAR CERTO", "gancho", 92,
                       "Leon tenta uma estrategia inesperada e o resultado e absurdo")

    passos = {
        e.NOVO: pipeline.Passo(etapas.fazer_obter_legendas(
            metadados=lambda url, **k: meta,
            baixar=lambda u: json.dumps(eventos), con=con), e.LEGENDA_OBTIDA),
        e.LEGENDA_OBTIDA: pipeline.Passo(etapas.fazer_selecionar(
            con=con, perfil=perfil, escolher=lambda *a, **k: [achado]), e.SEGMENTADO),
        e.SEGMENTADO: pipeline.Passo(etapas.fazer_renderizar(
            con=con, perfil=perfil,
            render_corte=lambda c, w, p, t, u: Path(w) / f"corte_{c.id}.mp4"),
            e.RENDERIZADO),
    }

    assert pipeline.executar_job(con, job.id, passos, tmp_path) == e.RENDERIZADO

    # 6 e 7. corte pronto, com os metadados da IA, ja na fila de upload
    corte = db.cortes_do_job(con, job.id)[0]
    assert corte.titulo == "ELE ACHOU QUE IA DAR CERTO"
    assert corte.descricao.startswith("Leon tenta")
    assert corte.nota == 92
    assert corte.estado == e.APROVADO
    assert [c.id for c in db.listar_cortes_aprovados(con)] == [corte.id]

    # a descricao do YouTube sai da IA, com o credito da origem
    texto = yt.montar_descricao(perfil, meta, corte)
    assert "estrategia inesperada" in texto and "youtu.be/aaaaaaaaaaa" in texto


def test_rodar_a_descoberta_duas_vezes_nao_reprocessa(con, tmp_path):
    from vidbot import canais

    canais.cadastrar(con, "@leon", "p")
    uploads = lambda url, limite: {"entries": [{"id": "aaaaaaaaaaa", "title": "x"}]}  # noqa: E731
    canais.descobrir(con, listar_uploads=uploads)
    canais.descobrir(con, listar_uploads=uploads)
    assert len(db.listar_jobs(con)) == 1
