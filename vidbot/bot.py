"""Telegram: dispara, acompanha e aprova.

O bot enfileira; nao processa. Handler que renderiza video trava o bot inteiro.
"""
from __future__ import annotations

import logging
from pathlib import Path

from . import db, estados as e, youtube as yt

log = logging.getLogger(__name__)

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


def montar_texto_corte(corte) -> str:
    return (f"corte #{corte.id} · {corte.titulo}\n"
            f"{corte.inicio_s:.0f}s -> {corte.fim_s:.0f}s "
            f"({corte.duracao_s:.0f}s) · nota {corte.nota}")


def publicar_ou_avisar(con, corte, perfil, meta: dict, servico) -> str:
    """Tenta publicar um corte ja aprovado; traduz o resultado numa linha pro operador.

    `servico` e None quando o canal do perfil nao tem token OAuth configurado
    (Perfil.canal_token vazio ou arquivo ausente) — nesse caso o corte fica
    aprovado, so nao ha como publicar ainda.
    """
    if servico is None:
        return "aprovado, mas o canal esta sem token OAuth configurado — nao publicado"
    try:
        video_id = yt.publicar(con, corte, perfil, meta, servico)
        return f"publicado: https://youtu.be/{video_id}"
    except yt.SemQuota:
        return "aprovado, mas a cota de upload do dia acabou — sera publicado quando houver cota"
    except yt.NaoAprovado as erro:
        return f"nao publicado: {erro}"


def _meta_do_job(cfg, job) -> dict:
    """Le o meta.json salvo por etapas.fazer_obter_legendas; cai pro job se faltar."""
    import json

    caminho = Path(cfg.work_dir) / str(job.id) / "meta.json"
    if caminho.exists():
        return json.loads(caminho.read_text(encoding="utf-8"))
    return {"url_original": job.url, "canal": job.canal_origem}


def _servico_do_perfil(perfil, tokens_dir: Path):
    if not perfil.canal_token:
        return None
    caminho = tokens_dir / perfil.canal_token
    if not caminho.exists():
        return None
    return yt.servico_real(caminho)


async def _cortes(update, context) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    dados = context.bot_data
    if not autorizado(update.effective_user.id, dados["cfg"]):
        await update.message.reply_text("nao autorizado")
        return
    pendentes = db.listar_cortes_pendentes(dados["con"])
    if not pendentes:
        await update.message.reply_text("nenhum corte aguardando aprovacao")
        return
    for corte in pendentes:
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton(rotulo, callback_data=cb) for rotulo, cb in linha]
            for linha in teclado_do_corte(corte.id)
        ])
        await update.message.reply_text(montar_texto_corte(corte), reply_markup=teclado)


async def _decisao(update, context) -> None:
    query = update.callback_query
    dados = context.bot_data
    if not autorizado(update.effective_user.id, dados["cfg"]):
        await query.answer("nao autorizado")
        return

    lido = ler_callback(query.data)
    if lido is None:
        await query.answer("callback invalido")
        return
    acao, corte_id = lido
    con = dados["con"]

    try:
        destino = decidir_corte(con, acao, corte_id)
    except JaDecidido:
        await query.answer("esse corte ja foi decidido")
        return
    except ValueError:
        await query.answer("acao desconhecida")
        return

    corte = db.obter_corte(con, corte_id)
    if destino != e.APROVADO:
        await query.edit_message_text(f"{montar_texto_corte(corte)}\n\nestado: {destino}")
        await query.answer()
        return

    job = db.obter_job(con, corte.job_id)
    perfil = dados["perfis"].get(job.perfil, dados["perfil_padrao"])
    meta = _meta_do_job(dados["cfg"], job)
    servico = _servico_do_perfil(perfil, dados["tokens_dir"])
    resultado = publicar_ou_avisar(con, corte, perfil, meta, servico)
    await query.edit_message_text(f"{montar_texto_corte(corte)}\n\n{resultado}")
    await query.answer()


def criar_app(cfg, con, perfis_dir: Path = Path("perfis"), tokens_dir: Path = Path("tokens")):
    """Monta a Application do python-telegram-bot. Nunca coberto por teste
    unitario (e so cola pra API real); a logica de decisao esta acima, testada."""
    from telegram.ext import Application, CallbackQueryHandler, CommandHandler

    from . import perfis as mod_perfis
    from .etapas import PERFIL_PADRAO

    app = Application.builder().token(cfg.telegram_token).build()
    app.bot_data.update(
        cfg=cfg, con=con, tokens_dir=Path(tokens_dir), perfil_padrao=PERFIL_PADRAO,
        perfis=mod_perfis.carregar_todos(perfis_dir) if Path(perfis_dir).is_dir() else {},
    )
    app.add_handler(CommandHandler("cortes", _cortes))
    app.add_handler(CallbackQueryHandler(_decisao))
    return app
