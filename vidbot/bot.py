"""Telegram: dispara, acompanha e aprova.

O bot enfileira; nao processa. Handler que renderiza video trava o bot inteiro.
"""
from __future__ import annotations

import html
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
    if destino == e.REFAZER:
        _reenfileirar_render(con, corte_id)
    return destino


def _reenfileirar_render(con, corte_id: int) -> None:
    """Devolve o corte para a fila de renderizacao.

    Sem isto REFAZER seria um beco sem saida: o corte sairia da lista e nada
    o traria de volta. Apagar o `caminho` faz `fazer_renderizar` deixar de
    pular esse corte, e o job volta a SEGMENTADO para a etapa rodar de novo.
    """
    db.definir_caminho_corte(con, corte_id, None)
    db.transicionar_corte(con, corte_id, e.REFAZER, e.AGUARDANDO_APROVACAO)
    corte = db.obter_corte(con, corte_id)
    job = db.obter_job(con, corte.job_id) if corte else None
    if job is not None and job.estado == e.RENDERIZADO:
        db.transicionar_job(con, job.id, e.RENDERIZADO, e.SEGMENTADO)


def teclado_do_corte(corte_id: int) -> list[list[tuple[str, str]]]:
    """(rotulo, callback_data) — convertido em InlineKeyboard pelo chamador."""
    return [[
        ("Publicar", f"aprovar:{corte_id}"),
        ("Refazer", f"refazer:{corte_id}"),
        ("Descartar", f"descartar:{corte_id}"),
    ]]


def tempo_hms(segundos: float) -> str:
    """mm:ss em video curto, hh:mm:ss quando passa da hora.

    Num episodio de 2h, `5022s` nao diz nada; `01:23:42` localiza o trecho.
    """
    total = max(0, int(segundos))
    horas, resto = divmod(total, 3600)
    minutos, seg = divmod(resto, 60)
    if horas:
        return f"{horas:02d}:{minutos:02d}:{seg:02d}"
    return f"{minutos:02d}:{seg:02d}"


def montar_texto_corte(corte, job=None) -> str:
    """Cartao de um corte. Escapa tudo que veio do modelo: o parse_mode e
    HTML e um `<` solto no titulo quebraria a mensagem inteira."""
    titulo = html.escape(corte.titulo or "sem titulo")
    linhas = [f"<b>{titulo}</b>",
              f"corte #{corte.id} · nota {corte.nota}/100"]

    descricao = html.escape(getattr(corte, "descricao", "") or "")
    if descricao:
        linhas += ["", descricao]

    linhas += ["",
               f"⏱ {tempo_hms(corte.inicio_s)} → {tempo_hms(corte.fim_s)}"
               f" ({corte.duracao_s:.0f}s)"]
    if job is not None:
        origem = html.escape(job.titulo or "")
        canal = html.escape(job.canal_origem or "")
        linhas.append(f"📺 {canal}{' · ' if canal and origem else ''}{origem}")
    return "\n".join(linhas)


def montar_ajuda() -> str:
    return (
        "<b>Fábrica de cortes</b>\n"
        "Eu observo os canais cadastrados, acho os melhores trechos dos vídeos "
        "novos e monto os Shorts. Você só decide o que vai ao ar.\n\n"
        "/cortes — os cortes prontos esperando sua decisão\n"
        "/status — panorama da fábrica (canais, fila, cota do dia)\n"
        "/canais — os canais que estou monitorando\n"
        "/fila — cortes aprovados que ainda não subiram\n"
        "/ajuda — esta mensagem\n\n"
        "Em cada corte você recebe o vídeo e três botões: "
        "<b>Publicar</b> sobe no YouTube, <b>Refazer</b> devolve para nova "
        "renderização e <b>Descartar</b> joga fora."
    )


def montar_status(con) -> str:
    from . import canais as mod_canais

    ativos = len(mod_canais.listar(con, so_ativos=True))
    total_canais = len(mod_canais.listar(con))
    pendentes = len(db.listar_cortes_pendentes(con, limite=999))
    fila = len(db.listar_cortes_aprovados(con, limite=999))
    restantes = yt.uploads_restantes(con, yt.hoje())

    em_curso = con.execute(
        "SELECT COUNT(*) c FROM jobs WHERE estado IN (?,?,?)",
        (e.NOVO, e.LEGENDA_OBTIDA, e.SEGMENTADO)).fetchone()["c"]

    return (
        "<b>Status da fábrica</b>\n\n"
        f"📡 {ativos} canal(is) ativo(s) de {total_canais} cadastrado(s)\n"
        f"⚙️ {em_curso} vídeo(s) em processamento\n"
        f"🎬 {pendentes} corte(s) aguardando sua aprovação\n"
        f"📤 {fila} na fila de upload\n"
        f"📊 cota de hoje: {restantes} upload(s) restante(s)"
    )


def montar_texto_canais(con) -> str:
    from . import canais as mod_canais

    registrados = mod_canais.listar(con)
    if not registrados:
        return ("Nenhum canal monitorado ainda.\n\n"
                "No servidor, cadastre com:\n"
                "<code>main.py canais add @handle -p perfil</code>")
    linhas = ["<b>Canais monitorados</b>", ""]
    for c in registrados:
        marca = "🟢" if c.ativo else "⏸"
        nome = html.escape(c.nome or c.url)
        perfil = html.escape(c.perfil)
        visto = c.visto_em or "nunca"
        linhas.append(f"{marca} <b>{nome}</b> · perfil {perfil}\n"
                      f"    última varredura: {visto}")
    return "\n".join(linhas)


def montar_texto_fila(con) -> str:
    aprovados = db.listar_cortes_aprovados(con, limite=50)
    if not aprovados:
        return "Nenhum corte esperando upload."
    restantes = yt.uploads_restantes(con, yt.hoje())
    linhas = [f"<b>Fila de upload</b> ({len(aprovados)}) · "
              f"cota hoje: {restantes}", ""]
    for c in aprovados:
        linhas.append(f"#{c.id} · {html.escape(c.titulo or 'sem titulo')}")
    return "\n".join(linhas)


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


HTML = "HTML"
# Bots sobem no maximo 50 MB pela Bot API; acima disso mandamos so o cartao.
LIMITE_VIDEO = 50 * 1024 * 1024


async def _porteiro(update, context):
    """Devolve a mensagem quando o autor pode falar comigo; None caso contrario."""
    mensagem = update.effective_message
    if mensagem is None:
        return None
    if not autorizado(_quem(update), context.bot_data["cfg"]):
        await mensagem.reply_text(
            "Você não está na lista de operadores deste bot.")
        return None
    return mensagem


def _teclado(corte_id):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(rotulo, callback_data=cb) for rotulo, cb in linha]
        for linha in teclado_do_corte(corte_id)
    ])


async def _enviar_corte(mensagem, con, corte) -> None:
    """Manda o video com o cartao na legenda; cai para so texto se nao der.

    Aprovar sem ver o video e o pior default possivel, entao o arquivo vem
    junto sempre que couber no limite da Bot API.
    """
    job = db.obter_job(con, corte.job_id)
    texto = montar_texto_corte(corte, job)
    teclado = _teclado(corte.id)

    caminho = Path(corte.caminho) if corte.caminho else None
    cabe = (caminho is not None and caminho.is_file()
            and caminho.stat().st_size <= LIMITE_VIDEO)
    if cabe:
        try:
            with caminho.open("rb") as video:
                await mensagem.reply_video(
                    video, caption=texto, parse_mode=HTML,
                    reply_markup=teclado, supports_streaming=True)
            return
        except Exception as erro:  # noqa: BLE001 - o cartao ainda tem valor
            log.warning("nao consegui enviar o video do corte %s: %s", corte.id, erro)

    aviso = "" if caminho is None else "\n\n<i>(vídeo grande demais para o Telegram)</i>"
    await mensagem.reply_text(texto + aviso, parse_mode=HTML, reply_markup=teclado)


async def _cortes(update, context) -> None:
    mensagem = await _porteiro(update, context)
    if mensagem is None:
        return
    con = context.bot_data["con"]
    pendentes = db.listar_cortes_pendentes(con)
    if not pendentes:
        await mensagem.reply_text(
            "Nenhum corte esperando decisão agora. Use /status para ver a fábrica.")
        return
    await mensagem.reply_text(
        f"{len(pendentes)} corte(s) esperando sua decisão:")
    for corte in pendentes:
        await _enviar_corte(mensagem, con, corte)


async def _ajuda(update, context) -> None:
    mensagem = await _porteiro(update, context)
    if mensagem is not None:
        await mensagem.reply_text(montar_ajuda(), parse_mode=HTML)


async def _status(update, context) -> None:
    mensagem = await _porteiro(update, context)
    if mensagem is not None:
        await mensagem.reply_text(
            montar_status(context.bot_data["con"]), parse_mode=HTML)


async def _canais(update, context) -> None:
    mensagem = await _porteiro(update, context)
    if mensagem is not None:
        await mensagem.reply_text(
            montar_texto_canais(context.bot_data["con"]), parse_mode=HTML)


async def _fila(update, context) -> None:
    mensagem = await _porteiro(update, context)
    if mensagem is not None:
        await mensagem.reply_text(
            montar_texto_fila(context.bot_data["con"]), parse_mode=HTML)


async def _desconhecido(update, context) -> None:
    mensagem = await _porteiro(update, context)
    if mensagem is not None:
        await mensagem.reply_text(
            "Não conheço esse comando.\n\n" + montar_ajuda(), parse_mode=HTML)


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
    job = db.obter_job(con, corte.job_id)
    rotulo = {e.REJEITADO: "🗑 descartado",
              e.REFAZER: "🔁 marcado para refazer"}.get(destino, destino)
    if destino != e.APROVADO:
        await _fechar(query, f"{montar_texto_corte(corte, job)}\n\n<b>{rotulo}</b>")
        await query.answer()
        return

    # O upload e sincrono e pode levar minutos: fora da thread do loop, senao
    # o bot inteiro congela e o proprio callback expira antes da resposta.
    await query.answer("publicando...")
    await _fechar(query, f"{montar_texto_corte(corte, job)}\n\n⏳ <i>publicando…</i>")
    perfil = dados["perfis"].get(job.perfil, dados["perfil_padrao"])
    meta = yt.meta_do_job(dados["cfg"], job)
    resultado = await asyncio.to_thread(
        _publicar_bloqueante, dados["db_path"], corte, perfil, meta, dados["tokens_dir"])
    await _fechar(query,
                  f"{montar_texto_corte(corte, job)}\n\n{html.escape(resultado)}")


async def _fechar(query, texto: str) -> None:
    """Reescreve o cartao ja decidido e tira os botoes.

    O corte pode ter vindo como video: ai a mensagem tem legenda, nao texto,
    e `edit_message_text` falharia.
    """
    try:
        if query.message is not None and query.message.caption is not None:
            await query.edit_message_caption(caption=texto, parse_mode=HTML)
        else:
            await query.edit_message_text(texto, parse_mode=HTML)
    except Exception as erro:  # noqa: BLE001 - decisao ja foi gravada no banco
        log.warning("nao consegui atualizar o cartao: %s", erro)


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
    from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                              MessageHandler, filters)

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
    app.post_init = registrar_menu
    app.add_handler(CommandHandler("cortes", _cortes))
    app.add_handler(CommandHandler(["start", "ajuda", "help"], _ajuda))
    app.add_handler(CommandHandler("status", _status))
    app.add_handler(CommandHandler("canais", _canais))
    app.add_handler(CommandHandler("fila", _fila))
    app.add_handler(CallbackQueryHandler(_decisao))
    # Por ultimo: so pega o que nenhum comando acima reconheceu.
    app.add_handler(MessageHandler(filters.COMMAND, _desconhecido))
    return app


async def registrar_menu(app) -> None:
    """Preenche o menu de comandos do Telegram (o botao ao lado do campo)."""
    from telegram import BotCommand

    await app.bot.set_my_commands([
        BotCommand("cortes", "cortes esperando sua decisão"),
        BotCommand("status", "panorama da fábrica"),
        BotCommand("canais", "canais monitorados"),
        BotCommand("fila", "aprovados aguardando upload"),
        BotCommand("ajuda", "como eu funciono"),
    ])
