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


def test_excecao_com_concorrencia_reavalua_ao_inves_de_retornar_estado_nao_escrito(con, tmp_path, tmp_path_factory):
    """Quando outro processo muda o job antes do erro ser registrado, reavalua."""
    jid = _job(con)

    # Armazena se a etapa foi chamada
    etapa_chamada = {"count": 0}

    def explode(job, workdir):
        etapa_chamada["count"] += 1
        # Simula outro processo movendo o job ANTES da transição de erro
        con2 = db.conectar(tmp_path_factory.mktemp("db2") / "t.sqlite3")
        db.criar_job(con2, "https://y/w?v=A", "A", "Ep", "@x", 600, "p")  # cria estrutura
        # Na verdade, precisamos usar a mesma conexão para simular concorrência
        # A melhor forma é transicionar manualmente logo após o erro
        raise RuntimeError("erro simulado")

    # Para simular concorrência, vamos usar uma abordagem diferente:
    # Criamos um passo que falha, e depois manualmente movemos o job
    # DURANTE a execução usando um passo wrapper

    def passo_com_race(job, workdir):
        # Simula que outro processo moveu o job antes de registrarmos o erro
        # Mudamos para LEGENDA_OBTIDA (fora do NOVO)
        db.transicionar_job(con, jid, e.NOVO, e.LEGENDA_OBTIDA)
        # Agora o passo falha
        raise RuntimeError("erro após race")

    # Passamos um passos dict que só tem NOVO
    reg = []
    final = pipeline.executar_job(
        con, jid, {e.NOVO: pipeline.Passo(passo_com_race, e.LEGENDA_OBTIDA)}, tmp_path
    )

    # Como o job foi movido para LEGENDA_OBTIDA antes da exceção handler
    # tentar fazer a transição, a transição falhará (False return)
    # e o loop vai continuar. Como não há passo para LEGENDA_OBTIDA,
    # o executar_job vai retornar LEGENDA_OBTIDA (não ERRO)
    assert final == e.LEGENDA_OBTIDA
    # E o job ainda deve estar em LEGENDA_OBTIDA, não em ERRO
    assert db.obter_job(con, jid).estado == e.LEGENDA_OBTIDA


def test_pula_para_com_concorrencia_reavalua_ao_inves_de_retornar_estado_nao_escrito(con, tmp_path, tmp_path_factory):
    """Quando outro processo muda o job antes do PulaPara ser registrado, reavalua."""
    jid = _job(con)

    def pula_com_race(job, workdir):
        # Simula que outro processo moveu o job antes de registrarmos o pulo
        db.transicionar_job(con, jid, e.NOVO, e.LEGENDA_OBTIDA)
        # Agora o passo pula
        raise pipeline.PulaPara(e.SEM_LEGENDA)

    # Passamos um passos dict que só tem NOVO
    final = pipeline.executar_job(
        con, jid, {e.NOVO: pipeline.Passo(pula_com_race, e.LEGENDA_OBTIDA)}, tmp_path
    )

    # Como o job foi movido para LEGENDA_OBTIDA antes do PulaPara handler
    # tentar fazer a transição para SEM_LEGENDA, a transição falhará (False return)
    # e o loop vai continuar. Como não há passo para LEGENDA_OBTIDA,
    # o executar_job vai retornar LEGENDA_OBTIDA (não SEM_LEGENDA)
    assert final == e.LEGENDA_OBTIDA
    # E o job deve estar em LEGENDA_OBTIDA, não em SEM_LEGENDA
    assert db.obter_job(con, jid).estado == e.LEGENDA_OBTIDA
