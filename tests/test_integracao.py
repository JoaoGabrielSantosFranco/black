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
