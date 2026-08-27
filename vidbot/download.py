"""yt-dlp como biblioteca. Duas fases: metadados/legendas, depois so os trechos."""
from __future__ import annotations

import time
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.utils import download_range_func

FORMATO = "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/b[height<=1080]/b"


class DownloadVazio(RuntimeError):
    """O yt-dlp terminou sem deixar arquivo algum no destino."""


def opcoes_metadados() -> dict:
    return {"skip_download": True, "quiet": True, "no_warnings": True,
            "writesubtitles": False, "writeautomaticsub": False}


def opcoes_secao(inicio_s: float, fim_s: float, destino: Path,
                 progresso=None) -> dict:
    op = {
        "format": FORMATO,
        "outtmpl": str(destino),
        "quiet": True,
        "no_warnings": True,
        "download_ranges": download_range_func(None, [(float(inicio_s), float(fim_s))]),
        "force_keyframes_at_cuts": True,
        # Sem fixar o container, um merge de streams incompativeis vira .mkv
        # e o caminho que devolvemos apontaria para um arquivo inexistente.
        "merge_output_format": "mp4",
    }
    if progresso is not None:
        op["progress_hooks"] = [progresso]
    return op


def metadados(url: str, ydl=None) -> dict:
    """Normaliza o dicionario do yt-dlp no formato que o pipeline usa."""
    if ydl is None:
        with YoutubeDL(opcoes_metadados()) as y:
            bruto = y.extract_info(url, download=False)
    else:
        bruto = ydl.extract_info(url, download=False)
    return {
        "video_id": bruto.get("id", ""),
        "titulo": bruto.get("title", "") or "",
        "canal": bruto.get("channel", "") or bruto.get("uploader", "") or "",
        "duracao_s": int(bruto.get("duration") or 0),
        "capitulos": bruto.get("chapters") or [],
        "url_original": bruto.get("webpage_url", url),
        "subtitles": bruto.get("subtitles") or {},
        "automatic_captions": bruto.get("automatic_captions") or {},
    }


def com_retentativa(chamada, tentativas: int = 3, espera=time.sleep):
    """3 tentativas com backoff. Video privado ou removido nao melhora
    esperando, entao so erro transitorio e retentado."""
    ultimo = None
    for n in range(tentativas):
        try:
            return chamada()
        except Exception as erro:  # noqa: BLE001
            texto = str(erro).lower()
            if any(m in texto for m in ("private", "unavailable", "removed", "members-only")):
                raise
            ultimo = erro
            if n < tentativas - 1:
                espera(2 ** n)
    raise ultimo


def baixar_secao(url: str, inicio_s: float, fim_s: float, destino: Path,
                 ydl=None, progresso=None) -> Path:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    opcoes = opcoes_secao(inicio_s, fim_s, destino, progresso)

    def _baixar():
        if ydl is None:
            with YoutubeDL(opcoes) as y:
                y.download([url])
        else:
            ydl.download([url])

    com_retentativa(_baixar)
    return _arquivo_baixado(destino)


def _arquivo_baixado(destino: Path) -> Path:
    """Confere que o download deixou arquivo e devolve o que realmente saiu.

    O yt-dlp pode remuxar para outro container ("merged into mkv") e gravar
    com sufixo diferente do pedido. Devolver o caminho pedido sem conferir
    empurraria o problema para o ffmpeg, com um erro que nao explica nada.
    """
    if destino.is_file():
        return destino
    irmaos = sorted(p for p in destino.parent.glob(f"{destino.stem}.*")
                    if p.is_file() and not p.name.endswith(".part"))
    if irmaos:
        return irmaos[0]
    raise DownloadVazio(f"o yt-dlp nao deixou arquivo em {destino}")
