"""Canais monitorados: cadastro e descoberta de videos novos.

E a porta de entrada da fabrica. O operador so diz quais canais observar;
daqui em diante cada video novo vira um job sozinho.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from . import db
from .urls import extrair_video_id

log = logging.getLogger(__name__)

HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
HANDLE = re.compile(r"^@[A-Za-z0-9._-]{1,60}$")
# /@handle, /channel/UC..., /c/nome e /user/nome sao as formas que o YouTube usa.
CAMINHO_CANAL = re.compile(r"^/(?:@[A-Za-z0-9._-]+|(?:channel|c|user)/[A-Za-z0-9._-]+)")


@dataclass
class Canal:
    id: int
    url: str
    nome: str
    perfil: str
    ativo: bool
    visto_em: str | None


def normalizar(bruto: str) -> str | None:
    """Leva qualquer forma de endereco de canal para a aba /videos.

    Devolve None para o que nao for canal — link de video inclusive, que e o
    engano mais provavel de quem cadastra.
    """
    texto = (bruto or "").strip()
    if not texto:
        return None
    if HANDLE.fullmatch(texto):
        return f"https://www.youtube.com/{texto}/videos"

    try:
        p = urlparse(texto)
    except ValueError:
        return None
    if p.netloc not in HOSTS or extrair_video_id(texto) is not None:
        return None

    m = CAMINHO_CANAL.match(p.path)
    if not m:
        return None
    base = m.group(0).rstrip("/")
    return f"https://www.youtube.com{base}/videos"


def cadastrar(con, bruto: str, perfil: str, nome: str = "") -> int:
    """Registra (ou reaponta) um canal. Recadastrar so troca o perfil."""
    url = normalizar(bruto)
    if url is None:
        raise ValueError(f"nao reconheci um canal do YouTube em: {bruto!r}")
    existente = con.execute("SELECT id FROM canais WHERE url=?", (url,)).fetchone()
    if existente:
        con.execute("UPDATE canais SET perfil=?, ativo=1 WHERE id=?",
                    (perfil, existente["id"]))
        return existente["id"]
    cur = con.execute(
        "INSERT INTO canais (url, nome, perfil) VALUES (?,?,?)",
        (url, nome or nome_da_url(url), perfil))
    return cur.lastrowid


def nome_da_url(url: str) -> str:
    """@handle ou o ultimo segmento — so para a listagem ficar legivel."""
    partes = [p for p in urlparse(url).path.split("/") if p and p != "videos"]
    return partes[-1] if partes else url


def listar(con, so_ativos: bool = False) -> list[Canal]:
    sql = "SELECT * FROM canais"
    if so_ativos:
        sql += " WHERE ativo=1"
    sql += " ORDER BY id"
    return [_canal(r) for r in con.execute(sql).fetchall()]


def definir_ativo(con, canal_id: int, ativo: bool) -> bool:
    cur = con.execute("UPDATE canais SET ativo=? WHERE id=?",
                      (1 if ativo else 0, canal_id))
    return cur.rowcount == 1


def remover(con, canal_id: int) -> bool:
    return con.execute("DELETE FROM canais WHERE id=?", (canal_id,)).rowcount == 1


def opcoes_uploads(limite: int) -> dict:
    """`extract_flat` devolve so a lista de ids, sem visitar cada video."""
    return {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist",
            "playlistend": int(limite), "skip_download": True}


def listar_uploads_real(url: str, limite: int = 10) -> dict:
    from yt_dlp import YoutubeDL

    with YoutubeDL(opcoes_uploads(limite)) as y:
        return y.extract_info(url, download=False) or {}


def descobrir(con, listar_uploads=listar_uploads_real, limite: int = 10) -> list[db.Job]:
    """Varre os canais ativos e cria um job por video ainda nao visto.

    Um canal que falha (privado, fora do ar, rede) nao pode impedir os
    outros de serem varridos — dai o try por canal.
    """
    criados: list[db.Job] = []
    for canal in listar(con, so_ativos=True):
        try:
            info = listar_uploads(canal.url, limite) or {}
        except Exception as erro:  # noqa: BLE001 - isolar o canal
            log.warning("canal %s falhou na descoberta: %s", canal.url, erro)
            continue

        for entrada in info.get("entries") or []:
            if not isinstance(entrada, dict):
                continue
            video_id = _id_da_entrada(entrada)
            if video_id is None or _ja_existe(con, video_id):
                continue
            job_id = db.criar_job(
                con, f"https://youtu.be/{video_id}", video_id,
                str(entrada.get("title") or "")[:300], canal.nome, 0, canal.perfil)
            criados.append(db.obter_job(con, job_id))
        marcar_visto(con, canal.id)
    return criados


def _id_da_entrada(entrada: dict) -> str | None:
    """Aceita tanto o `id` achatado quanto uma url completa."""
    bruto = entrada.get("id")
    if isinstance(bruto, str) and re.fullmatch(r"[A-Za-z0-9_-]{11}", bruto):
        return bruto
    return extrair_video_id(str(entrada.get("url") or ""))


def _ja_existe(con, video_id: str) -> bool:
    return con.execute(
        "SELECT 1 FROM jobs WHERE video_id=? LIMIT 1", (video_id,)).fetchone() is not None


def marcar_visto(con, canal_id: int) -> None:
    con.execute("UPDATE canais SET visto_em=datetime('now') WHERE id=?", (canal_id,))


def _canal(r) -> Canal:
    return Canal(r["id"], r["url"], r["nome"], r["perfil"], bool(r["ativo"]), r["visto_em"])
