"""Maquina de estados do job. Conhece a ordem, nunca o 'como'."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import db, estados as e

Etapa = Callable[[db.Job, Path], None]


@dataclass
class Passo:
    etapa: Etapa
    proximo: str


class PulaPara(Exception):
    """Etapa desviou para um estado final (ex.: SEM_LEGENDA)."""

    def __init__(self, estado: str):
        super().__init__(estado)
        self.estado = estado


def workdir_de(raiz: Path, job_id: int) -> Path:
    d = Path(raiz) / str(job_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def executar_job(con, job_id: int, passos: dict[str, Passo], raiz: Path) -> str:
    """Avanca o job ate um estado sem passo. Devolve o estado final.

    Retomavel: comeca do estado atual, nao do inicio. Se cair no meio do
    render, a proxima execucao recomeca de SEGMENTADO.
    """
    while True:
        job = db.obter_job(con, job_id)
        if job is None:
            raise ValueError(f"job {job_id} nao existe")
        passo = passos.get(job.estado)
        if passo is None:
            return job.estado

        origem = job.estado
        try:
            passo.etapa(job, workdir_de(raiz, job_id))
        except PulaPara as desvio:
            if not db.transicionar_job(con, job_id, origem, desvio.estado):
                # Outro processo mexeu no job. Reavalia do zero em vez de assumir.
                continue
            return desvio.estado
        except Exception as erro:  # noqa: BLE001 - a mensagem vai para o banco
            if not db.transicionar_job(con, job_id, origem, e.ERRO, erro=str(erro)[:500]):
                # Outro processo mexeu no job. Reavalia do zero em vez de assumir.
                continue
            return e.ERRO

        if not db.transicionar_job(con, job_id, origem, passo.proximo):
            # Outro processo mexeu no job. Reavalia do zero em vez de assumir.
            continue
