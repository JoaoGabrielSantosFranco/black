"""Transcricao -> trechos candidatos -> filtro deterministico.

O LLM sugere e da nota; quem decide e o filtro. Nota de modelo sozinha nao
basta: duracao, sobreposicao e bordas sao regra, nao opiniao.
"""
from __future__ import annotations

import bisect
import logging
from dataclasses import dataclass, replace

from . import llm, validate as v
from .captions import Palavra, Transcricao

log = logging.getLogger(__name__)

SISTEMA = """Voce escolhe trechos de podcast que funcionam como video curto.
Responda SOMENTE JSON: {"trechos": [{"inicio": s, "fim": s, "titulo": "...",
"gancho": "primeira frase", "nota": 0-100, "motivo": "..."}]}

Um bom trecho: e uma ideia autocontida, entendida sem o resto do episodio;
tem comeco e fim naturais; prende nos 3 primeiros segundos; dura 20 a 90s.
Use os tempos exatos da transcricao. Nao invente falas."""


@dataclass
class Candidato:
    inicio_s: float
    fim_s: float
    titulo: str
    gancho: str
    nota: int

    @property
    def duracao_s(self) -> float:
        return self.fim_s - self.inicio_s


def coagir(bruto: dict) -> list[Candidato]:
    saida = []
    for item in bruto.get("trechos") or []:
        if not isinstance(item, dict):
            continue
        ini = v.numero(item.get("inicio"), 0, 86400, -1, cast=float)
        fim = v.numero(item.get("fim"), 0, 86400, -1, cast=float)
        if ini < 0 or fim <= ini:
            continue
        saida.append(Candidato(
            ini, fim,
            v.texto(item.get("titulo"), "sem titulo", 95),
            v.texto(item.get("gancho"), "", 200),
            v.numero(item.get("nota"), 0, 100, 50),
        ))
    return saida


def ajustar_bordas(c: Candidato, palavras: list[Palavra]) -> Candidato:
    """Encosta as bordas nos limites de palavra para nao cortar no meio."""
    if not palavras:
        return c
    inicios = [p.inicio_s for p in palavras]
    i = min(bisect.bisect_left(inicios, c.inicio_s), len(palavras) - 1)
    j = bisect.bisect_right(inicios, c.fim_s) - 1
    j = max(0, min(j, len(palavras) - 1))
    return replace(c, inicio_s=palavras[i].inicio_s, fim_s=palavras[j].fim_s)


def _sobreposicao(a: Candidato, b: Candidato) -> float:
    comum = min(a.fim_s, b.fim_s) - max(a.inicio_s, b.inicio_s)
    menor = min(a.duracao_s, b.duracao_s)
    return max(0.0, comum) / menor if menor > 0 else 0.0


def filtrar(cands: list[Candidato], *, min_s: float = 20.0, max_s: float = 90.0,
            max_cortes: int = 12, sobrep_max: float = 0.3) -> list[Candidato]:
    validos = [c for c in cands if min_s <= c.duracao_s <= max_s]
    validos.sort(key=lambda c: c.nota, reverse=True)
    escolhidos: list[Candidato] = []
    for c in validos:
        if any(_sobreposicao(c, j) > sobrep_max for j in escolhidos):
            continue
        escolhidos.append(c)
        if len(escolhidos) >= max_cortes:
            break
    return escolhidos


def janelas(palavras: list[Palavra], *, max_chars: int = 12000,
            sobrep_chars: int = 1000) -> list[list[Palavra]]:
    """Fatia a transcricao em janelas sobrepostas que cabem no contexto."""
    if not palavras:
        return []
    saida, atual, tamanho = [], [], 0
    for p in palavras:
        atual.append(p)
        tamanho += len(p.texto) + 1
        if tamanho >= max_chars:
            saida.append(atual)
            recuo, acumulado = [], 0
            for anterior in reversed(atual):
                recuo.insert(0, anterior)
                acumulado += len(anterior.texto) + 1
                if acumulado >= sobrep_chars:
                    break
            atual, tamanho = list(recuo), acumulado
    if atual and (not saida or atual is not saida[-1]):
        saida.append(atual)
    return saida


def _transcrever_janela(janela: list[Palavra]) -> str:
    return "\n".join(f"[{p.inicio_s:.1f}] {p.texto}" for p in janela)


def escolher(t: Transcricao, meta: dict, cfg,
             perguntar=llm.perguntar_json, **opcoes) -> list[Candidato]:
    """Percorre as janelas, junta os candidatos e aplica o filtro."""
    brutos: list[Candidato] = []
    janelas_list = list(janelas(t.palavras))
    falhas, ultima_erro = 0, None
    for janela in janelas_list:
        prompt = (f"Episodio: {meta.get('titulo', '')}\n"
                  f"Transcricao (segundo entre colchetes):\n"
                  f"{_transcrever_janela(janela)}")
        try:
            brutos.extend(coagir(perguntar(prompt, SISTEMA, cfg)))
        except Exception as e:  # noqa: BLE001 - uma janela ruim nao derruba o episodio
            falhas += 1
            ultima_erro = e
            log.warning(f"janela falhou: {e}")
            continue
    # Se todas as janelas falharam, e uma falha sistêmica, não 'sem clips'
    if janelas_list and falhas == len(janelas_list):
        raise RuntimeError("todas as janelas falharam") from ultima_erro
    ajustados = [ajustar_bordas(c, t.palavras) for c in brutos]
    return filtrar(ajustados, **opcoes)
