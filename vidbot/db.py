"""Estado duravel em SQLite. Toda transicao e atomica e validada."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import estados as e

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT NOT NULL,
    video_id      TEXT NOT NULL,
    titulo        TEXT NOT NULL DEFAULT '',
    canal_origem  TEXT NOT NULL DEFAULT '',
    duracao_s     INTEGER NOT NULL DEFAULT 0,
    perfil        TEXT NOT NULL,
    estado        TEXT NOT NULL,
    erro          TEXT,
    criado_em     TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS cortes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    inicio_s   REAL NOT NULL,
    fim_s      REAL NOT NULL,
    titulo     TEXT NOT NULL DEFAULT '',
    nota       INTEGER NOT NULL DEFAULT 0,
    estado     TEXT NOT NULL,
    caminho    TEXT,
    youtube_id TEXT,
    erro       TEXT
);
CREATE TABLE IF NOT EXISTS uploads (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    corte_id INTEGER NOT NULL REFERENCES cortes(id),
    youtube_id TEXT NOT NULL,
    dia      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_jobs_estado ON jobs(estado);
CREATE INDEX IF NOT EXISTS ix_cortes_job ON cortes(job_id);
CREATE INDEX IF NOT EXISTS ix_uploads_dia ON uploads(dia);
"""


class TransicaoInvalida(ValueError):
    """Transicao que o mapa de estados nao permite. Sempre um bug, nunca dado ruim."""


@dataclass
class Job:
    id: int
    url: str
    video_id: str
    titulo: str
    canal_origem: str
    duracao_s: int
    perfil: str
    estado: str
    erro: str | None
    criado_em: str


@dataclass
class Corte:
    id: int
    job_id: int
    inicio_s: float
    fim_s: float
    titulo: str
    nota: int
    estado: str
    caminho: str | None
    youtube_id: str | None
    erro: str | None

    @property
    def duracao_s(self) -> float:
        return self.fim_s - self.inicio_s


def conectar(caminho: Path) -> sqlite3.Connection:
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    return con


# ---------------------------------------------------------------- jobs

def criar_job(con, url, video_id, titulo, canal_origem, duracao_s, perfil) -> int:
    cur = con.execute(
        "INSERT INTO jobs (url, video_id, titulo, canal_origem, duracao_s, perfil, estado)"
        " VALUES (?,?,?,?,?,?,?)",
        (url, video_id, titulo, canal_origem, duracao_s, perfil, e.NOVO),
    )
    return cur.lastrowid


def obter_job(con, job_id: int) -> Job | None:
    r = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _job(r) if r else None


def proximo_job(con, estados: list[str]) -> Job | None:
    marc = ",".join("?" * len(estados))
    r = con.execute(
        f"SELECT * FROM jobs WHERE estado IN ({marc}) ORDER BY id LIMIT 1", estados
    ).fetchone()
    return _job(r) if r else None


def listar_jobs(con, limite: int = 20) -> list[Job]:
    """Jobs mais recentes primeiro, para a CLI e o bot."""
    rs = con.execute(
        "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (int(limite),)
    ).fetchall()
    return [_job(r) for r in rs]


def transicionar_job(con, job_id: int, de: str, para: str, erro: str | None = None) -> bool:
    """True se aplicou. False se o job ja nao estava em `de` (outro processo mexeu)."""
    if not e.pode(e.TRANSICOES_JOB, de, para):
        raise TransicaoInvalida(f"job: {de} -> {para}")
    cur = con.execute(
        "UPDATE jobs SET estado=?, erro=?, atualizado_em=datetime('now')"
        " WHERE id=? AND estado=?",
        (para, erro, job_id, de),
    )
    return cur.rowcount == 1


# ---------------------------------------------------------------- cortes

def criar_corte(con, job_id, inicio_s, fim_s, titulo, nota) -> int:
    cur = con.execute(
        "INSERT INTO cortes (job_id, inicio_s, fim_s, titulo, nota, estado)"
        " VALUES (?,?,?,?,?,?)",
        (job_id, float(inicio_s), float(fim_s), titulo, int(nota), e.AGUARDANDO_APROVACAO),
    )
    return cur.lastrowid


def obter_corte(con, corte_id: int) -> Corte | None:
    r = con.execute("SELECT * FROM cortes WHERE id=?", (corte_id,)).fetchone()
    return _corte(r) if r else None


def cortes_do_job(con, job_id: int) -> list[Corte]:
    rs = con.execute(
        "SELECT * FROM cortes WHERE job_id=? ORDER BY inicio_s", (job_id,)
    ).fetchall()
    return [_corte(r) for r in rs]


def listar_cortes_pendentes(con, limite: int = 20) -> list[Corte]:
    """Cortes aguardando decisao humana, de qualquer job, mais recentes primeiro."""
    rs = con.execute(
        "SELECT * FROM cortes WHERE estado=? ORDER BY id DESC LIMIT ?",
        (e.AGUARDANDO_APROVACAO, int(limite)),
    ).fetchall()
    return [_corte(r) for r in rs]


def transicionar_corte(con, corte_id: int, de: str, para: str, erro: str | None = None) -> bool:
    if not e.pode(e.TRANSICOES_CORTE, de, para):
        raise TransicaoInvalida(f"corte: {de} -> {para}")
    cur = con.execute(
        "UPDATE cortes SET estado=?, erro=? WHERE id=? AND estado=?",
        (para, erro, corte_id, de),
    )
    return cur.rowcount == 1


def definir_caminho_corte(con, corte_id: int, caminho: str) -> None:
    con.execute("UPDATE cortes SET caminho=? WHERE id=?", (caminho, corte_id))


# ---------------------------------------------------------------- quota

def registrar_upload(con, corte_id: int, youtube_id: str, dia: str) -> None:
    con.execute(
        "INSERT INTO uploads (corte_id, youtube_id, dia) VALUES (?,?,?)",
        (corte_id, youtube_id, dia),
    )
    con.execute("UPDATE cortes SET youtube_id=? WHERE id=?", (youtube_id, corte_id))


def uploads_no_dia(con, dia: str) -> int:
    return con.execute("SELECT COUNT(*) c FROM uploads WHERE dia=?", (dia,)).fetchone()["c"]


# ---------------------------------------------------------------- helpers

def _job(r) -> Job:
    return Job(r["id"], r["url"], r["video_id"], r["titulo"], r["canal_origem"],
               r["duracao_s"], r["perfil"], r["estado"], r["erro"], r["criado_em"])


def _corte(r) -> Corte:
    return Corte(r["id"], r["job_id"], r["inicio_s"], r["fim_s"], r["titulo"],
                 r["nota"], r["estado"], r["caminho"], r["youtube_id"], r["erro"])
