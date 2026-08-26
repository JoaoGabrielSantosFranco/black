"""Extracao do id de video a partir das formas de URL do YouTube."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

ID = r"[A-Za-z0-9_-]{11}"
CAMINHO = re.compile(rf"^/(?:shorts|live|embed|v)/({ID})")
HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}


def extrair_video_id(url: str) -> str | None:
    try:
        p = urlparse(url.strip())
    except ValueError:
        return None
    if p.netloc in {"youtu.be", "www.youtu.be"}:
        candidato = p.path.lstrip("/")
        return candidato if re.fullmatch(ID, candidato) else None
    if p.netloc not in HOSTS:
        return None
    if p.path == "/watch":
        v = parse_qs(p.query).get("v", [""])[0]
        return v if re.fullmatch(ID, v) else None
    m = CAMINHO.match(p.path)
    return m.group(1) if m else None
