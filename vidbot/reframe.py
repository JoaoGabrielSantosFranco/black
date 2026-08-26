"""16:9 -> 9:16. Centro por padrao; rosto quando o perfil pedir.

Falha de deteccao cai para centro em silencio: degradar e melhor que falhar.
"""
from __future__ import annotations

import logging
from pathlib import Path

from . import validate as v

log = logging.getLogger(__name__)
# `split` (dois rostos empilhados) esta no spec §5 mas NAO foi implementado aqui:
# fica fora da whitelist de proposito, para cair em `centro` de forma previsivel
# em vez de aceitar o valor e ignorar o efeito.
ESTRATEGIAS = {"centro", "rosto"}
SAIDA_L, SAIDA_A = 1080, 1920


def filtro_vertical(estrategia: str, largura: int, altura: int,
                    centro_x: float | None = None) -> str:
    """Cadeia de filtros ffmpeg que leva o quadro para 1080x1920."""
    modo = v.escolha(estrategia, ESTRATEGIAS, "centro")
    recorte_l = min(largura, round(altura * 9 / 16))
    if modo == "rosto" and centro_x is not None:
        alvo = v.numero(centro_x, 0.0, 1.0, 0.5, cast=float)
        x = int(round(alvo * largura - recorte_l / 2))
        x = max(0, min(x, largura - recorte_l))
    else:
        x = (largura - recorte_l) // 2
    return f"crop={recorte_l}:{altura}:{x}:0,scale={SAIDA_L}:{SAIDA_A}"


def detectar_rosto_x(video: Path, largura: int, amostras: int = 5) -> float | None:
    """Fracao horizontal do rosto dominante, ou None. Nunca levanta."""
    try:
        import cv2
    except ImportError:
        return None
    try:
        cascata = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        captura = cv2.VideoCapture(str(video))
        total = int(captura.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        centros = []
        for i in range(amostras):
            captura.set(cv2.CAP_PROP_POS_FRAMES, int(total * (i + 0.5) / amostras))
            ok, quadro = captura.read()
            if not ok:
                continue
            cinza = cv2.cvtColor(quadro, cv2.COLOR_BGR2GRAY)
            rostos = cascata.detectMultiScale(cinza, 1.2, 5)
            if len(rostos):
                x, _, w, _ = max(rostos, key=lambda r: r[2] * r[3])
                centros.append((x + w / 2) / largura)
        captura.release()
        return sum(centros) / len(centros) if centros else None
    except Exception as erro:  # noqa: BLE001 - deteccao e opcional
        log.warning("deteccao de rosto falhou, usando centro: %s", erro)
        return None
