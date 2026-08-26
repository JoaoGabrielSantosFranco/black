from pathlib import Path

import pytest

from vidbot import db, estados as e, pipeline


@pytest.fixture
def con(tmp_path):
    c = db.conectar(tmp_path / "t.sqlite3")
    yield c
    c.close()


def _job(con):
    return db.criar_job(con, "https://y/w?v=A", "A", "Ep", "@x", 600, "p")


def _passos(registro, pula_em=None):
    def faz(nome):
        def etapa(job, workdir):
            registro.append(nome)
            if pula_em == nome:
                raise pipeline.PulaPara(e.SEM_LEGENDA)
        return etapa
    return {
        e.NOVO: pipeline.Passo(faz("legenda"), e.LEGENDA_OBTIDA),
        e.LEGENDA_OBTIDA: pipeline.Passo(faz("segmenta"), e.SEGMENTADO),
        e.SEGMENTADO: pipeline.Passo(faz("render"), e.RENDERIZADO),
    }


def test_roda_as_etapas_na_ordem(con, tmp_path):
    reg = []
    final = pipeline.executar_job(con, _job(con), _passos(reg), tmp_path)
    assert reg == ["legenda", "segmenta", "render"]
    assert final == e.RENDERIZADO


def test_retoma_do_estado_atual_sem_refazer_o_que_ja_passou(con, tmp_path):
    jid = _job(con)
    db.transicionar_job(con, jid, e.NOVO, e.LEGENDA_OBTIDA)
    reg = []
    pipeline.executar_job(con, jid, _passos(reg), tmp_path)
    assert reg == ["segmenta", "render"]


def test_pula_para_encerra_no_estado_pedido(con, tmp_path):
    reg = []
    final = pipeline.executar_job(con, _job(con), _passos(reg, pula_em="legenda"), tmp_path)
    assert final == e.SEM_LEGENDA
    assert reg == ["legenda"]


def test_excecao_leva_o_job_para_erro_com_a_mensagem(con, tmp_path):
    def explode(job, workdir):
        raise RuntimeError("yt-dlp caiu")

    jid = _job(con)
    final = pipeline.executar_job(
        con, jid, {e.NOVO: pipeline.Passo(explode, e.LEGENDA_OBTIDA)}, tmp_path
    )
    assert final == e.ERRO
    assert "yt-dlp caiu" in db.obter_job(con, jid).erro


def test_workdir_existe_quando_a_etapa_roda(con, tmp_path):
    visto = {}

    def etapa(job, workdir):
        visto["existe"] = workdir.is_dir()

    pipeline.executar_job(
        con, _job(con), {e.NOVO: pipeline.Passo(etapa, e.LEGENDA_OBTIDA)}, tmp_path
    )
    assert visto["existe"] is True


def test_estado_sem_passo_encerra_sem_erro(con, tmp_path):
    jid = _job(con)
    db.transicionar_job(con, jid, e.NOVO, e.LEGENDA_OBTIDA)
    assert pipeline.executar_job(con, jid, {}, tmp_path) == e.LEGENDA_OBTIDA
