"""Um YAML por canal de destino. Tudo validado na entrada."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import validate as v

REENQUADRES = {"centro", "rosto"}  # `split` do spec §5 fica para depois
PRIVACIDADES = {"private", "unlisted", "public"}
POSICOES = {"topo", "centro", "base"}


@dataclass
class Perfil:
    nome: str
    canal_token: str = ""
    reenquadre: str = "centro"
    max_cortes: int = 12
    min_s: float = 20.0
    max_s: float = 90.0
    privacidade: str = "unlisted"
    creditar_origem: bool = True
    cadencia: str = ""
    idiomas: list[str] = field(default_factory=lambda: ["pt", "en"])
    estilo: dict = field(default_factory=dict)


def _estilo(bruto) -> dict:
    b = bruto if isinstance(bruto, dict) else {}
    return {
        "fonte": v.texto(b.get("fonte"), "DejaVu Sans", 60),
        "tamanho": v.numero(b.get("tamanho"), 20, 130, 72),
        "cor_texto": v.cor_hex(b.get("cor_texto"), "#FFFFFF"),
        "cor_destaque": v.cor_hex(b.get("cor_destaque"), "#FFD400"),
        "cor_contorno": v.cor_hex(b.get("cor_contorno"), "#000000"),
        "contorno": v.numero(b.get("contorno"), 0, 8, 4),
        "posicao": v.escolha(b.get("posicao"), POSICOES, "centro"),
        "maiusculas": v.flag(b.get("maiusculas"), True),
        "caixa": v.flag(b.get("caixa"), False),
        "palavras_por_cue": v.numero(b.get("palavras_por_cue"), 1, 8, 3),
    }


def carregar(caminho: Path) -> Perfil:
    dados = yaml.safe_load(Path(caminho).read_text(encoding="utf-8")) or {}
    idiomas = dados.get("idiomas")
    return Perfil(
        nome=v.texto(dados.get("nome"), Path(caminho).stem, 60),
        canal_token=v.texto(dados.get("canal_token"), "", 120),
        reenquadre=v.escolha(dados.get("reenquadre"), REENQUADRES, "centro"),
        max_cortes=v.numero(dados.get("max_cortes"), 1, 30, 12),
        min_s=v.numero(dados.get("min_s"), 5, 120, 20, cast=float),
        max_s=v.numero(dados.get("max_s"), 10, 180, 90, cast=float),
        privacidade=v.escolha(dados.get("privacidade"), PRIVACIDADES, "unlisted"),
        creditar_origem=v.flag(dados.get("creditar_origem"), True),
        cadencia=v.texto(dados.get("cadencia"), "", 40),
        idiomas=[str(i)[:5] for i in idiomas] if isinstance(idiomas, list) and idiomas
                else ["pt", "en"],
        estilo=_estilo(dados.get("estilo")),
    )


def carregar_todos(diretorio: Path) -> dict[str, Perfil]:
    saida = {}
    for arq in sorted(Path(diretorio).glob("*.yaml")):
        p = carregar(arq)
        saida[p.nome] = p
    return saida
