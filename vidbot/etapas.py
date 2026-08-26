"""As etapas reais do pipeline, com as dependencias injetaveis.

Cada `fazer_*` devolve a etapa ja amarrada, o que permite testar a orquestracao
sem rede e sem ffmpeg. `montar` liga tudo com as implementacoes de producao.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

from . import (captions, db, download, estados as e, perfis, pipeline,
               reframe, render, segment, subtitles)

log = logging.getLogger(__name__)
PERFIL_PADRAO = perfis.Perfil(nome="padrao")
ARQ_TRANSCRICAO = "transcricao.json"


def _salvar_transcricao(workdir: Path, t: captions.Transcricao) -> None:
    (Path(workdir) / ARQ_TRANSCRICAO).write_text(json.dumps({
        "origem": t.origem, "idioma": t.idioma,
        "palavras": [asdict(p) for p in t.palavras],
    }, ensure_ascii=False), encoding="utf-8")


def _ler_transcricao(workdir: Path) -> captions.Transcricao:
    d = json.loads((Path(workdir) / ARQ_TRANSCRICAO).read_text(encoding="utf-8"))
    return captions.Transcricao(
        [captions.Palavra(**p) for p in d["palavras"]], d["origem"], d["idioma"])


def fazer_obter_legendas(metadados=download.metadados, baixar=None,
                         con=None, idiomas=("pt", "en")):
    def etapa(job, workdir: Path) -> None:
        meta = metadados(job.url)
        if con is not None:
            con.execute(
                "UPDATE jobs SET titulo=?, canal_origem=?, duracao_s=? WHERE id=?",
                (meta["titulo"], meta["canal"], meta["duracao_s"], job.id))
        (Path(workdir) / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8")

        obter = baixar or _baixar_url
        transcricao = captions.obter(meta, obter, list(idiomas))
        if transcricao is None:
            raise pipeline.PulaPara(e.SEM_LEGENDA)
        _salvar_transcricao(workdir, transcricao)

    return etapa


def _baixar_url(url: str) -> str:
    import requests
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.text


def fazer_selecionar(con, escolher=segment.escolher, cfg=None,
                     perfil: perfis.Perfil = PERFIL_PADRAO):
    def etapa(job, workdir: Path) -> None:
        transcricao = _ler_transcricao(workdir)
        meta = json.loads((Path(workdir) / "meta.json").read_text(encoding="utf-8")) \
            if (Path(workdir) / "meta.json").exists() else {"titulo": job.titulo}
        candidatos = escolher(transcricao, meta, cfg,
                              criterios=perfil.criterios,
                              min_s=perfil.min_s, max_s=perfil.max_s,
                              max_cortes=perfil.max_cortes)
        if not candidatos:
            raise pipeline.PulaPara(e.SEM_CORTES)
        for c in candidatos:
            db.criar_corte(con, job.id, c.inicio_s, c.fim_s, c.titulo, c.nota,
                           descricao=c.descricao)

    return etapa


def _render_corte_real(corte, workdir: Path, perfil: perfis.Perfil,
                       transcricao: captions.Transcricao, url: str) -> Path:
    bruto = Path(workdir) / f"corte_{corte.id}_bruto.mp4"
    download.baixar_secao(url, corte.inicio_s, corte.fim_s, bruto)

    janela = [captions.Palavra(p.texto, p.inicio_s - corte.inicio_s,
                               p.fim_s - corte.inicio_s)
              for p in transcricao.palavras
              if corte.inicio_s <= p.inicio_s < corte.fim_s]
    ass = Path(workdir) / f"corte_{corte.id}.ass"
    ass.write_text(subtitles.gerar_ass(janela, perfil.estilo,
                                       karaoke=transcricao.por_palavra),
                   encoding="utf-8")

    centro = (reframe.detectar_rosto_x(bruto, 1920)
              if perfil.reenquadre == "rosto" else None)
    filtro = reframe.filtro_vertical(perfil.reenquadre, 1920, 1080, centro)
    return render.renderizar(bruto, ass, Path(workdir) / f"corte_{corte.id}.mp4", filtro)


def fazer_renderizar(con, render_corte=_render_corte_real,
                     perfil: perfis.Perfil = PERFIL_PADRAO):
    """`render_corte(corte, workdir, perfil, transcricao, url) -> Path`."""
    def etapa(job, workdir: Path) -> None:
        transcricao = (_ler_transcricao(workdir)
                       if (Path(workdir) / ARQ_TRANSCRICAO).exists()
                       else captions.Transcricao([], "asr", "pt"))
        for corte in db.cortes_do_job(con, job.id):
            if corte.caminho:
                continue  # ja renderizado numa execucao anterior
            try:
                saida = render_corte(corte, workdir, perfil, transcricao, job.url)
                db.definir_caminho_corte(con, corte.id, str(saida))
                if perfil.auto_publicar:
                    # Canal sem revisao humana: o corte ja entra na fila de
                    # upload. So aqui, depois do render dar certo.
                    db.transicionar_corte(con, corte.id, e.AGUARDANDO_APROVACAO,
                                          e.APROVADO)
            except Exception as erro:  # noqa: BLE001 - isolar o corte
                log.warning("corte %s falhou: %s", corte.id, erro)
                db.transicionar_corte(con, corte.id, e.AGUARDANDO_APROVACAO,
                                      e.ERRO_RENDER, erro=str(erro)[:300])

    return etapa


def montar(con, cfg, perfil: perfis.Perfil) -> dict[str, pipeline.Passo]:
    return {
        e.NOVO: pipeline.Passo(
            fazer_obter_legendas(con=con, idiomas=tuple(perfil.idiomas)),
            e.LEGENDA_OBTIDA),
        e.LEGENDA_OBTIDA: pipeline.Passo(
            fazer_selecionar(con=con, cfg=cfg, perfil=perfil), e.SEGMENTADO),
        e.SEGMENTADO: pipeline.Passo(
            fazer_renderizar(con=con, perfil=perfil), e.RENDERIZADO),
    }
