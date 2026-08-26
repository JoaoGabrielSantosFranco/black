"""Trechos + estilo do perfil -> arquivo .ass queimado pelo ffmpeg.

O LLM nunca escreve ASS. O estilo vem do perfil e passa por clamp e whitelist
antes de virar texto: estilo hostil produz um arquivo feio, nunca invalido.
"""
from __future__ import annotations

from . import validate as v
from .captions import Palavra
from .perfis import POSICOES

ALINHAMENTO = {"topo": 8, "centro": 5, "base": 2}

CABECALHO = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: P,{fonte},{tamanho},{cor_texto},{cor_destaque},{cor_contorno},&H80000000,-1,0,{borda},{contorno},1,{alinhamento},60,60,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def cor_ass(hex_rgb: str) -> str:
    """#RRGGBB -> &H00BBGGRR (ASS usa BGR com alfa na frente)."""
    seguro = v.cor_hex(hex_rgb, "#FFFFFF").lstrip("#")
    r, g, b = seguro[0:2], seguro[2:4], seguro[4:6]
    return f"&H00{b}{g}{r}".upper()


def tempo_ass(segundos: float) -> str:
    s = max(0.0, float(segundos))
    h, resto = divmod(s, 3600)
    m, seg = divmod(resto, 60)
    return f"{int(h)}:{int(m):02d}:{seg:05.2f}"


def agrupar(palavras: list[Palavra], por_cue: int) -> list[list[Palavra]]:
    n = max(1, int(por_cue))
    return [palavras[i:i + n] for i in range(0, len(palavras), n)]


def _linha(grupo: list[Palavra], maiusculas: bool, karaoke: bool) -> str:
    if karaoke:
        partes = []
        for p in grupo:
            centesimos = max(1, round((p.fim_s - p.inicio_s) * 100))
            texto = p.texto.upper() if maiusculas else p.texto
            partes.append(f"{{\\k{centesimos}}}{texto}")
        return " ".join(partes)
    texto = " ".join(p.texto for p in grupo)
    return texto.upper() if maiusculas else texto


def gerar_ass(palavras: list[Palavra], estilo: dict, *, karaoke: bool) -> str:
    cabecalho = CABECALHO.format(
        fonte=v.texto(estilo.get("fonte"), "DejaVu Sans", 60),
        tamanho=v.numero(estilo.get("tamanho"), 20, 130, 72),
        cor_texto=cor_ass(estilo.get("cor_texto")),
        cor_destaque=cor_ass(estilo.get("cor_destaque")),
        cor_contorno=cor_ass(estilo.get("cor_contorno")),
        contorno=v.numero(estilo.get("contorno"), 0, 8, 4),
        borda=3 if v.flag(estilo.get("caixa"), False) else 1,
        alinhamento=ALINHAMENTO[v.escolha(estilo.get("posicao"), POSICOES, "centro")],
    )
    maiusculas = v.flag(estilo.get("maiusculas"), True)
    por_cue = v.numero(estilo.get("palavras_por_cue"), 1, 8, 3)

    eventos = []
    for grupo in agrupar(palavras, por_cue):
        if not grupo:
            continue
        texto = _linha(grupo, maiusculas, karaoke).replace("\n", " ")
        eventos.append(
            f"Dialogue: 0,{tempo_ass(grupo[0].inicio_s)},{tempo_ass(grupo[-1].fim_s)},"
            f"P,,0,0,0,,{texto}"
        )
    return cabecalho + "\n".join(eventos) + "\n"
