"""ffmpeg: aplica o reenquadre e queima a legenda."""
from __future__ import annotations

import subprocess
from pathlib import Path


class FalhaFFmpeg(RuntimeError):
    """ffmpeg terminou com codigo diferente de zero. Carrega o stderr."""


def montar_comando(entrada: Path, ass: Path, saida: Path, filtro: str) -> list[str]:
    escapado = str(ass).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(entrada),
        "-vf", f"{filtro},ass='{escapado}'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(saida),
    ]


def renderizar(entrada: Path, ass: Path, saida: Path, filtro: str,
               progresso=None) -> Path:
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    cmd = montar_comando(Path(entrada), Path(ass), saida, filtro)
    if progresso is not None:
        cmd[1:1] = ["-progress", "pipe:1"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise FalhaFFmpeg(f"codigo {proc.returncode}: {proc.stderr.strip()[:400]}")
    return saida


def gerar_video_de_teste(destino: Path, segundos: int = 2) -> Path:
    """Video sintetico para o teste de fumaca. Nao usado em producao."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc=size=1920x1080:rate=30:duration={segundos}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={segundos}",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
        "-shortest", str(destino),
    ], check=True, capture_output=True)
    return destino
