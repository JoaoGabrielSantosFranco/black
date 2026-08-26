"""Telegram: dispara, acompanha e aprova.

O bot enfileira; nao processa. Handler que renderiza video trava o bot inteiro.
"""
from __future__ import annotations

import logging
from pathlib import Path

from . import config, db, estados as e, youtube as yt

log = logging.getLogger(__name__)

ACOES = {
    "aprovar": e.APROVADO,
    "descartar": e.REJEITADO,
    "refazer": e.REFAZER,
}


class JaDecidido(RuntimeError):
    """O corte saiu de AGUARDANDO_APROVACAO antes deste toque."""


def autorizado(user_id: int | None, cfg) -> bool:
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
        return ("aprovado, mas o canal esta sem token OAuth configurado — "
                "rode `main.py publicar` depois de configurar")
    try:
        video_id = yt.publicar(con, corte, perfil, meta, servico)
        return f"publicado: https://youtu.be/{video_id}"
    except yt.SemQuota:
        return ("aprovado, mas a cota de upload do dia acabou — "
                "rode `main.py publicar` amanha para drenar")
    except yt.NaoAprovado as erro:
        return f"nao publicado: {erro}"
    except Exception as erro:  # noqa: BLE001 - falha de rede/API nao pode prender o corte
        # Sem isto o corte fica preso em APROVADO: um novo toque cai em
        # JaDecidido e nada jamais marca ERRO_UPLOAD, que existe justamente
        # para permitir a retentativa.
        log.warning("upload do corte %s falhou: %s", corte.id, erro)
        db.transicionar_corte(con, corte.id, e.APROVADO, e.ERRO_UPLOAD,
                              erro=str(erro)[:300])
        return f"upload falhou: {str(erro)[:200]}"


def _quem(update) -> int | None:
    """Id do autor, ou None em update sem usuario (post de canal, por exemplo)."""
    usuario = update.effective_user
    return usuario.id if usuario is not None else None


async def _cortes(update, context) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    dados = context.bot_data
    mensagem = update.effective_message
    if mensagem is None:
        return
    if not autorizado(_quem(update), dados["cfg"]):
        await mensagem.reply_text("nao autorizado")
        return
    pendentes = db.listar_cortes_pendentes(dados["con"])
    if not pendentes:
        await mensagem.reply_text("nenhum corte aguardando aprovacao")
        return
    for corte in pendentes:
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton(rotulo, callback_data=cb) for rotulo, cb in linha]
            for linha in teclado_do_corte(corte.id)
        ])
        await mensagem.reply_text(montar_texto_corte(corte), reply_markup=teclado)


async def _decisao(update, context) -> None:
    import asyncio

    query = update.callback_query
    dados = context.bot_data
    if not autorizado(_quem(update), dados["cfg"]):
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

    # O upload e sincrono e pode levar minutos: fora da thread do loop, senao
    # o bot inteiro congela e o proprio callback expira antes da resposta.
    await query.answer("publicando...")
    job = db.obter_job(con, corte.job_id)
    perfil = dados["perfis"].get(job.perfil, dados["perfil_padrao"])
    meta = yt.meta_do_job(dados["cfg"], job)
    resultado = await asyncio.to_thread(
        _publicar_bloqueante, dados["db_path"], corte, perfil, meta, dados["tokens_dir"])
    await query.edit_message_text(f"{montar_texto_corte(corte)}\n\n{resultado}")


def _publicar_bloqueante(db_path, corte, perfil, meta, tokens_dir) -> str:
    """Resolve o cliente OAuth e sobe o video. Roda fora do event loop.

    Abre a propria conexao: a do loop pertence a outra thread e o sqlite3
    recusa uso cruzado (`check_same_thread`).
    """
    con = db.conectar(db_path)
    try:
        try:
            servico = yt.servico_do_perfil(perfil, tokens_dir)
        except Exception as erro:  # noqa: BLE001 - token corrompido/expirado
            log.warning("nao consegui montar o cliente do canal %s: %s", perfil.nome, erro)
            return f"aprovado, mas o token do canal falhou: {str(erro)[:200]}"
        return publicar_ou_avisar(con, corte, perfil, meta, servico)
    finally:
        con.close()


def criar_app(cfg, con, db_path, perfis_dir: Path | None = None,
              tokens_dir: Path | None = None):
    """Monta a Application do python-telegram-bot. Nunca coberto por teste
    unitario (e so cola pra API real); a logica de decisao esta acima, testada.

    `perfis_dir`/`tokens_dir` caem na raiz do projeto, nao no CWD: o bot
    costuma subir por systemd/cron de um diretorio qualquer, e resolver por
    CWD faria todo perfil virar o padrao (sem token, nunca publica).
    """
    from telegram.ext import Application, CallbackQueryHandler, CommandHandler

    from . import perfis as mod_perfis
    from .etapas import PERFIL_PADRAO

    perfis_dir = Path(perfis_dir) if perfis_dir else config.RAIZ / "perfis"
    tokens_dir = Path(tokens_dir) if tokens_dir else config.RAIZ / "tokens"
    if not perfis_dir.is_dir():
        log.warning("diretorio de perfis nao encontrado em %s — "
                    "todo job vai cair no perfil padrao, que nao publica", perfis_dir)

    app = Application.builder().token(cfg.telegram_token).build()
    app.bot_data.update(
        cfg=cfg, con=con, db_path=db_path, tokens_dir=tokens_dir,
        perfil_padrao=PERFIL_PADRAO,
        perfis=mod_perfis.carregar_todos(perfis_dir) if perfis_dir.is_dir() else {},
    )
    app.add_handler(CommandHandler("cortes", _cortes))
    app.add_handler(CallbackQueryHandler(_decisao))
    return app
