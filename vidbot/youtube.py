"""Upload multi-canal com contador de quota.

Quota esgotada nao perde aprovacao: o corte fica em APROVADO e o scheduler
o drena no dia seguinte.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from . import db, estados as e

QUOTA_DIARIA = 10000
CUSTO_UPLOAD = 1600


class SemQuota(RuntimeError):
    """A quota do dia acabou. O corte continua APROVADO."""


class NaoAprovado(RuntimeError):
    """Tentativa de publicar corte que nao passou por aprovacao humana."""


def hoje() -> str:
    return date.today().isoformat()


def uploads_restantes(con, dia: str) -> int:
    usados = db.uploads_no_dia(con, dia)
    return max(0, QUOTA_DIARIA // CUSTO_UPLOAD - usados)


def tem_quota(con, dia: str) -> bool:
    return uploads_restantes(con, dia) > 0


def montar_descricao(perfil, meta: dict, corte) -> str:
    partes = [corte.titulo]
    if perfil.creditar_origem:
        partes.append(
            f"\nTrecho do episodio original de {meta.get('canal', '')}:\n"
            f"{meta.get('url_original', '')}"
        )
    return "\n".join(p for p in partes if p).strip()


def publicar(con, corte, perfil, meta: dict, servico, dia: str | None = None) -> str:
    """Sobe o corte. `servico.inserir(corpo, caminho) -> video_id`."""
    dia = dia or hoje()
    if corte.estado != e.APROVADO:
        raise NaoAprovado(f"corte {corte.id} esta em {corte.estado}")
    if not tem_quota(con, dia):
        raise SemQuota(f"quota de {dia} esgotada")

    corpo = {
        "snippet": {
            "title": corte.titulo[:95],
            "description": montar_descricao(perfil, meta, corte)[:4900],
            "categoryId": "22",
        },
        "status": {"privacyStatus": perfil.privacidade,
                   "selfDeclaredMadeForKids": False},
    }
    video_id = servico.inserir(corpo, str(corte.caminho or ""))
    db.registrar_upload(con, corte.id, video_id, dia)
    db.transicionar_corte(con, corte.id, e.APROVADO, e.PUBLICADO)
    return video_id


def servico_real(token_path: Path):
    """Cliente autenticado da YouTube Data API. Nao usado em teste."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    cred = Credentials.from_authorized_user_file(
        str(token_path), ["https://www.googleapis.com/auth/youtube.upload"])
    if cred.expired and cred.refresh_token:
        cred.refresh(Request())
    api = build("youtube", "v3", credentials=cred, cache_discovery=False)

    class Servico:
        def inserir(self, corpo, caminho):
            midia = MediaFileUpload(caminho, chunksize=-1, resumable=True)
            req = api.videos().insert(part="snippet,status", body=corpo, media_body=midia)
            return req.execute()["id"]

    return Servico()
