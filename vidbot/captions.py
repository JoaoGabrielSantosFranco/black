"""Faixas de legenda do YouTube. Substitui transcricao propria.

ASR (json3) tem tempo por palavra e serve a sincronia da legenda.
A faixa do autor tem texto pontuado e serve a leitura e a selecao.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

TEMPO = re.compile(r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})")


@dataclass
class Palavra:
    texto: str
    inicio_s: float
    fim_s: float


@dataclass
class Transcricao:
    palavras: list[Palavra]
    origem: str   # "asr" | "autor"
    idioma: str

    @property
    def texto(self) -> str:
        return " ".join(p.texto for p in self.palavras)

    @property
    def por_palavra(self) -> bool:
        return self.origem == "asr"


def parse_json3(dados: dict) -> list[Palavra]:
    """json3 do ASR: tStartMs por evento, tOffsetMs por palavra."""
    brutas: list[Palavra] = []
    for ev in dados.get("events", []):
        base = ev.get("tStartMs", 0) / 1000.0
        fim_ev = base + ev.get("dDurationMs", 0) / 1000.0
        for seg in ev.get("segs", []):
            texto = seg.get("utf8", "").strip()
            if not texto:
                continue
            brutas.append(Palavra(texto, base + seg.get("tOffsetMs", 0) / 1000.0, fim_ev))
    for atual, seguinte in zip(brutas, brutas[1:]):
        atual.fim_s = seguinte.inicio_s
    return brutas


def _segundos(m: re.Match) -> float:
    h, mi, s, ms = (int(g) for g in m.groups())
    return h * 3600 + mi * 60 + s + ms / 1000.0


def parse_vtt(texto: str) -> list[Palavra]:
    """VTT/SRT: sem tempo por palavra, entao cada linha vira uma entrada."""
    saida: list[Palavra] = []
    blocos = re.split(r"\n\s*\n", texto.strip())
    for bloco in blocos:
        linhas = [l for l in bloco.splitlines() if l.strip()]
        marca = next((l for l in linhas if "-->" in l), None)
        if marca is None:
            continue
        tempos = list(TEMPO.finditer(marca))
        if len(tempos) < 2:
            continue
        corpo = " ".join(l.strip() for l in linhas[linhas.index(marca) + 1:])
        corpo = re.sub(r"<[^>]+>", "", corpo).strip()
        if corpo:
            saida.append(Palavra(corpo, _segundos(tempos[0]), _segundos(tempos[1])))
    return saida


def _melhor(faixas: list[dict]) -> str | None:
    for ext in ("json3", "vtt", "srv3", "srt"):
        for f in faixas:
            if f.get("ext") == ext and f.get("url"):
                return f["url"]
    return None


def escolher_faixa(info: dict, idiomas: list[str]) -> tuple[str, str, str] | None:
    """(url, origem, idioma). Autor antes de ASR; idioma na ordem pedida."""
    for origem, chave in (("autor", "subtitles"), ("asr", "automatic_captions")):
        disponiveis = info.get(chave) or {}
        for idioma in idiomas:
            for codigo, faixas in disponiveis.items():
                if codigo == idioma or codigo.startswith(f"{idioma}-"):
                    url = _melhor(faixas)
                    if url:
                        return url, origem, codigo
    return None


def obter(info: dict, baixar: Callable[[str], str],
          idiomas: list[str]) -> Transcricao | None:
    escolha = escolher_faixa(info, idiomas)
    if escolha is None:
        return None
    url, origem, idioma = escolha
    conteudo = baixar(url)
    try:
        palavras = parse_json3(json.loads(conteudo))
    except (json.JSONDecodeError, TypeError):
        palavras = parse_vtt(conteudo)
    return Transcricao(palavras, origem, idioma) if palavras else None
