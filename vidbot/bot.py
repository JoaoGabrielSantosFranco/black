"""Telegram: dispara, acompanha e aprova.

O bot enfileira; nao processa. Handler que renderiza video trava o bot inteiro.
"""
from __future__ import annotations

from . import db, estados as e

ACOES = {
    "aprovar": e.APROVADO,
    "descartar": e.REJEITADO,
    "refazer": e.REFAZER,
}


class JaDecidido(RuntimeError):
    """O corte saiu de AGUARDANDO_APROVACAO antes deste toque."""


def autorizado(user_id: int, cfg) -> bool:
    return bool(cfg.telegram_ids) and user_id in cfg.telegram_ids


def ler_callback(dado: str) -> tuple[str, int] | None:
    acao, _, bruto = (dado or "").partition(":")
    if acao not in ACOES or not bruto.isdigit():
        return None
    return acao, int(bruto)


def decidir_corte(con, acao: str, corte_id: int) -> str:
    """Aplica a decisao humana. Levanta se ja houve outra."""
    destino = ACOES.get(acao)
    if destino is None:
        raise ValueError(f"acao desconhecida: {acao}")
    if not db.transicionar_corte(con, corte_id, e.AGUARDANDO_APROVACAO, destino):
        raise JaDecidido(f"corte {corte_id} nao esta aguardando aprovacao")
    return destino


def teclado_do_corte(corte_id: int) -> list[list[tuple[str, str]]]:
    """(rotulo, callback_data) — convertido em InlineKeyboard pelo chamador."""
    return [[
        ("Publicar", f"aprovar:{corte_id}"),
        ("Refazer", f"refazer:{corte_id}"),
        ("Descartar", f"descartar:{corte_id}"),
    ]]
