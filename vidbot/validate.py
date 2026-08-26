"""Coercao defensiva de tudo que vem de LLM.

Nada daqui confia na saida do modelo: numero e grampeado, escolha passa por
whitelist, cor casa com regex. O pior caso e um padrao feio, nunca um arquivo
invalido ou um argumento perigoso de linha de comando.
"""
from __future__ import annotations

import json
import math
import re

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
CERCA = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


class SaidaInvalida(ValueError):
    """O modelo nao devolveu JSON aproveitavel."""


def extrair_json(texto: str) -> dict:
    bruto = (texto or "").strip()
    cerca = CERCA.search(bruto)
    if cerca:
        bruto = cerca.group(1).strip()
    try:
        dados = json.loads(bruto)
    except json.JSONDecodeError:
        ini, fim = bruto.find("{"), bruto.rfind("}")
        if ini == -1 or fim <= ini:
            raise SaidaInvalida(f"sem JSON: {bruto[:200]}") from None
        try:
            dados = json.loads(bruto[ini:fim + 1])
        except json.JSONDecodeError as erro:
            raise SaidaInvalida(str(erro)) from None
    if not isinstance(dados, dict):
        raise SaidaInvalida("JSON nao e objeto")
    return dados


def numero(valor, lo, hi, padrao, *, cast=int):
    try:
        bruto = float(valor)
    except (TypeError, ValueError):
        return cast(padrao)
    if not math.isfinite(bruto):
        return cast(padrao)
    return cast(min(hi, max(lo, bruto)))


def texto(valor, padrao: str = "", limite: int = 200) -> str:
    if not isinstance(valor, str) or not valor.strip():
        return padrao[:limite]
    return valor.strip()[:limite]


def escolha(valor, permitidos: set[str], padrao: str) -> str:
    if isinstance(valor, str) and valor.strip().lower() in permitidos:
        return valor.strip().lower()
    return padrao


def flag(valor, padrao: bool) -> bool:
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str):
        return valor.strip().lower() in {"true", "sim", "yes", "1"}
    return padrao


def cor_hex(valor, padrao: str) -> str:
    if isinstance(valor, str):
        candidato = valor.strip()
        if not candidato.startswith("#"):
            candidato = "#" + candidato
        if HEX.match(candidato):
            return candidato.upper()
    return padrao
