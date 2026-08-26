import json
from pathlib import Path

import pytest

from vidbot import db, estados as e, etapas, pipeline


@pytest.fixture
def con(tmp_path):
    c = db.conectar(tmp_path / "t.sqlite3")
    yield c
    c.close()


def _job(con):
    jid = db.criar_job(con, "https://youtu.be/A", "A", "", "", 0, "cortes_br")
    return db.obter_job(con, jid)


def test_sem_faixa_de_legenda_pula_para_sem_legenda(con, tmp_path):
    def meta(url, **kw):
        return {"video_id": "A", "titulo": "Ep", "canal": "@x", "duracao_s": 600,
                "capitulos": [], "url_original": url,
                "subtitles": {}, "automatic_captions": {}}

    etapa = etapas.fazer_obter_legendas(metadados=meta, baixar=lambda u: "")
    with pytest.raises(pipeline.PulaPara) as capturado:
        etapa(_job(con), tmp_path)
    assert capturado.value.estado == e.SEM_LEGENDA


def test_com_faixa_grava_a_transcricao_no_workdir(con, tmp_path):
    def meta(url, **kw):
        return {"video_id": "A", "titulo": "Ep", "canal": "@x", "duracao_s": 600,
                "capitulos": [], "url_original": url, "subtitles": {},
                "automatic_captions": {"pt": [{"ext": "json3", "url": "u"}]}}

    conteudo = json.dumps({"events": [
        {"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "oi", "tOffsetMs": 0}]}]})
    etapa = etapas.fazer_obter_legendas(metadados=meta, baixar=lambda u: conteudo)
    etapa(_job(con), tmp_path)
    salvo = json.loads((tmp_path / "transcricao.json").read_text())
    assert salvo["origem"] == "asr" and salvo["palavras"][0]["texto"] == "oi"


def test_metadados_do_episodio_sao_gravados_no_job(con, tmp_path):
    def meta(url, **kw):
        return {"video_id": "A", "titulo": "Episodio 148", "canal": "@x",
                "duracao_s": 6720, "capitulos": [], "url_original": url,
                "subtitles": {"pt": [{"ext": "vtt", "url": "u"}]},
                "automatic_captions": {}}

    job = _job(con)
    etapa = etapas.fazer_obter_legendas(
        metadados=meta,
        baixar=lambda u: "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\noi\n",
        con=con)
    etapa(job, tmp_path)
    assert db.obter_job(con, job.id).titulo == "Episodio 148"


def test_filtro_vazio_pula_para_sem_cortes(con, tmp_path):
    (tmp_path / "transcricao.json").write_text(json.dumps(
        {"origem": "asr", "idioma": "pt",
         "palavras": [{"texto": "x", "inicio_s": 0, "fim_s": 1}]}))
    etapa = etapas.fazer_selecionar(con=con, escolher=lambda *a, **k: [])
    with pytest.raises(pipeline.PulaPara) as capturado:
        etapa(_job(con), tmp_path)
    assert capturado.value.estado == e.SEM_CORTES


def test_selecao_grava_um_corte_por_candidato(con, tmp_path):
    from vidbot.segment import Candidato

    (tmp_path / "transcricao.json").write_text(json.dumps(
        {"origem": "asr", "idioma": "pt",
         "palavras": [{"texto": "x", "inicio_s": 0, "fim_s": 1}]}))
    job = _job(con)
    etapa = etapas.fazer_selecionar(con=con, escolher=lambda *a, **k: [
        Candidato(10, 50, "um", "g", 90), Candidato(100, 140, "dois", "g", 80)])
    etapa(job, tmp_path)
    assert [c.titulo for c in db.cortes_do_job(con, job.id)] == ["um", "dois"]


def test_falha_num_corte_nao_derruba_os_outros(con, tmp_path):
    job = _job(con)
    bons = [db.criar_corte(con, job.id, 0, 40, "a", 90),
            db.criar_corte(con, job.id, 100, 140, "b", 80)]

    def render_de_um_falha(corte, workdir, perfil, transcricao, url):
        if corte.id == bons[0]:
            raise RuntimeError("ffmpeg codigo 1")
        return workdir / "ok.mp4"

    etapa = etapas.fazer_renderizar(con=con, render_corte=render_de_um_falha,
                                    perfil=etapas.PERFIL_PADRAO)
    etapa(job, tmp_path)
    estados_finais = {c.id: c.estado for c in db.cortes_do_job(con, job.id)}
    assert estados_finais[bons[0]] == e.ERRO_RENDER
    assert estados_finais[bons[1]] == e.AGUARDANDO_APROVACAO


def _perfil(**kw):
    from vidbot import perfis
    return perfis.Perfil(nome="p", **kw)


def test_auto_publicar_deixa_o_corte_aprovado_direto(con, tmp_path):
    """Sem revisao humana o corte ja sai pronto para o dreno de upload."""
    job = _job(con)
    cid = db.criar_corte(con, job.id, 0, 40, "a", 90)
    etapa = etapas.fazer_renderizar(
        con=con, perfil=_perfil(auto_publicar=True),
        render_corte=lambda c, w, p, t, u: tmp_path / f"corte_{c.id}.mp4")
    etapa(job, tmp_path)
    assert db.obter_corte(con, cid).estado == e.APROVADO


def test_sem_auto_publicar_o_corte_espera_aprovacao(con, tmp_path):
    job = _job(con)
    cid = db.criar_corte(con, job.id, 0, 40, "a", 90)
    etapa = etapas.fazer_renderizar(
        con=con, perfil=_perfil(auto_publicar=False),
        render_corte=lambda c, w, p, t, u: tmp_path / f"corte_{c.id}.mp4")
    etapa(job, tmp_path)
    assert db.obter_corte(con, cid).estado == e.AGUARDANDO_APROVACAO


def test_auto_publicar_nao_aprova_corte_que_falhou_no_render(con, tmp_path):
    job = _job(con)
    cid = db.criar_corte(con, job.id, 0, 40, "a", 90)

    def quebra(c, w, p, t, u):
        raise RuntimeError("ffmpeg codigo 1")

    etapa = etapas.fazer_renderizar(
        con=con, perfil=_perfil(auto_publicar=True), render_corte=quebra)
    etapa(job, tmp_path)
    assert db.obter_corte(con, cid).estado == e.ERRO_RENDER
