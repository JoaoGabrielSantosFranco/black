"""Prompt em linguagem natural -> plano de video estruturado e validado.

O usuario descreve tudo numa frase no Telegram, incluindo o estilo da legenda:

    "3 videos sobre cachoeiras, tudo em preto e branco,
     legenda amarela bem grande no meio, palavra por palavra"

O LLM traduz isso no dicionario abaixo. Como modelos pequenos alucinam,
NADA que vem do LLM e usado cru: tudo passa por _coerce_* com clamp,
whitelist de enum e fallback para um padrao seguro.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .llm import ask_json

SYSTEM = """Voce e um diretor de video que traduz pedidos em JSON de configuracao.
Responda SOMENTE com JSON valido, sem comentarios e sem texto fora do JSON.

Esquema exato:
{
  "topic": "tema curto em ingles, para buscar clipes",
  "queries": ["3 a 6 termos de busca em INGLES, concretos e visuais"],
  "language": "codigo ISO do idioma da legenda, ex: pt",
  "script": ["frases curtas da narracao/legenda, 8-14 palavras cada"],
  "video": {
    "grayscale": bool,       // true se pediram preto e branco / P&B / dessaturado
    "aspect": "9:16" | "16:9" | "1:1",
    "clip_seconds": 3-8,     // duracao de cada corte
    "total_seconds": 15-90,
    "contrast": 0.8-1.5
  },
  "subtitle": {
    "font_size": 28-110,     // relativo a altura 1920; "grande" ~ 84, "pequena" ~ 42
    "primary_color": "#RRGGBB",     // cor do texto
    "highlight_color": "#RRGGBB",   // cor da palavra ativa no karaoke
    "outline_color": "#RRGGBB",
    "outline_width": 0-8,
    "position": "top" | "center" | "bottom",
    "uppercase": bool,
    "box": bool,             // true se pediram caixa/faixa preta ATRAS do texto
    "words_per_cue": 1-8,    // "palavra por palavra" => 1
    "karaoke": bool          // destacar a palavra sendo falada
  },
  "youtube": {
    "title": "titulo chamativo, ate 90 caracteres",
    "description": "2 a 4 frases",
    "tags": ["5 a 12 tags"]
  }
}

Regras:
- "queries" SEMPRE em ingles: os bancos de clipes gratuitos indexam em ingles.
- Respeite literalmente o estilo pedido. Se pediram "legenda amarela", use #FFD400.
- Se algo nao foi pedido, escolha um padrao bonito de video vertical viral.
"""

# ---------------------------------------------------------------- validacao

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _hex_color(value: Any, default: str) -> str:
    if isinstance(value, str):
        v = value.strip()
        if not v.startswith("#"):
            v = "#" + v
        if _HEX.match(v):
            return v.upper()
    return default


def _num(value: Any, lo: float, hi: float, default: float, *, cast=int):
    try:
        return cast(min(hi, max(lo, cast(float(value)))))
    except (TypeError, ValueError):
        return cast(default)


def _flag(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "sim", "yes", "1"}
    return default


def _choice(value: Any, allowed: set[str], default: str) -> str:
    if isinstance(value, str) and value.strip().lower() in allowed:
        return value.strip().lower()
    return default


def _str_list(value: Any, *, lo: int, hi: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out = [str(v).strip() for v in value if str(v).strip()]
    return out[:hi] if len(out) >= lo else out


# ---------------------------------------------------------------- dataclass


@dataclass
class VideoPlan:
    topic: str
    queries: list[str]
    language: str
    script: list[str]
    video: dict = field(default_factory=dict)
    subtitle: dict = field(default_factory=dict)
    youtube: dict = field(default_factory=dict)

    @property
    def clip_count(self) -> int:
        """Quantos clipes baixar para cobrir a duracao pedida, com folga."""
        per = self.video["clip_seconds"]
        return max(3, min(20, -(-self.video["total_seconds"] // per) + 2))


def _coerce(raw: dict, prompt: str) -> VideoPlan:
    v = raw.get("video") or {}
    s = raw.get("subtitle") or {}
    y = raw.get("youtube") or {}

    queries = _str_list(raw.get("queries"), lo=1, hi=6)
    if not queries:
        # Ultimo recurso: usa as palavras significativas do proprio prompt.
        queries = [w for w in re.findall(r"[a-zA-Z]{4,}", prompt)][:3] or ["nature"]

    script = _str_list(raw.get("script"), lo=1, hi=40)

    return VideoPlan(
        topic=str(raw.get("topic") or queries[0]).strip()[:120],
        queries=queries,
        language=str(raw.get("language") or "pt").strip()[:5],
        script=script,
        video={
            "grayscale": _flag(v.get("grayscale"), False),
            "aspect": _choice(v.get("aspect"), {"9:16", "16:9", "1:1"}, "9:16"),
            "clip_seconds": _num(v.get("clip_seconds"), 2, 12, 5),
            "total_seconds": _num(v.get("total_seconds"), 10, 180, 40),
            "contrast": _num(v.get("contrast"), 0.5, 2.0, 1.0, cast=float),
        },
        subtitle={
            "font_size": _num(s.get("font_size"), 20, 130, 72),
            "primary_color": _hex_color(s.get("primary_color"), "#FFFFFF"),
            "highlight_color": _hex_color(s.get("highlight_color"), "#FFD400"),
            "outline_color": _hex_color(s.get("outline_color"), "#000000"),
            "outline_width": _num(s.get("outline_width"), 0, 8, 4),
            "position": _choice(
                s.get("position"), {"top", "center", "bottom"}, "center"
            ),
            "uppercase": _flag(s.get("uppercase"), True),
            "box": _flag(s.get("box"), False),
            "words_per_cue": _num(s.get("words_per_cue"), 1, 8, 3),
            "karaoke": _flag(s.get("karaoke"), True),
        },
        youtube={
            "title": (str(y.get("title") or raw.get("topic") or "Video").strip())[:95],
            "description": str(y.get("description") or "").strip()[:4500],
            "tags": _str_list(y.get("tags"), lo=0, hi=12),
        },
    )


def build_plan(prompt: str) -> VideoPlan:
    """Traduz o prompt do usuario num VideoPlan validado."""
    raw = ask_json(prompt, SYSTEM)
    return _coerce(raw, prompt)
