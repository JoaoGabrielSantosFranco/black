"""CLI da fabrica de cortes. Nucleo puro: nao sabe quem o chamou."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from vidbot import config, db, estados as e, pipeline
from vidbot.urls import extrair_video_id


def _con(args):
    caminho = Path(args.db) if args.db else config.carregar().db_path
    return db.conectar(caminho)


def cmd_doctor(_args) -> int:
    cfg = config.carregar()
    problemas = 0
    for nome, ok, detalhe in config.diagnosticar(cfg):
        print(f"{'OK  ' if ok else 'FALTA'} {nome}: {detalhe}")
        problemas += 0 if ok else 1
    print("\ntudo pronto" if not problemas else f"\n{problemas} pendencia(s)")
    return 0 if not problemas else 1


def cmd_ingest(args) -> int:
    video_id = extrair_video_id(args.url)
    if video_id is None:
        print(f"link nao reconhecido como video do YouTube: {args.url}")
        return 1
    con = _con(args)
    try:
        job_id = db.criar_job(con, args.url, video_id, "", "", 0, args.perfil)
        print(f"job #{job_id} criado ({video_id}, perfil {args.perfil})")
        return 0
    finally:
        con.close()


def cmd_jobs(args) -> int:
    con = _con(args)
    try:
        jobs = db.listar_jobs(con)
        if not jobs:
            print("nenhum job")
            return 0
        for j in jobs:
            titulo = j.titulo or j.video_id
            print(f"#{j.id:>4} {j.estado:<20} {j.perfil:<12} {titulo}")
        return 0
    finally:
        con.close()


PENDENTES = [e.NOVO, e.LEGENDA_OBTIDA, e.SEGMENTADO]


def _perfis_dir() -> Path:
    """Ancorado na raiz, nao no CWD: cron e systemd rodam de qualquer lugar."""
    return config.RAIZ / "perfis"


def _perfil_do_job(job):
    from vidbot import etapas, perfis as mod_perfis

    todos = mod_perfis.carregar_todos(_perfis_dir()) if _perfis_dir().is_dir() else {}
    return todos.get(job.perfil) or etapas.PERFIL_PADRAO


def _avancar(con, cfg, job) -> str:
    from vidbot import etapas

    passos = etapas.montar(con, cfg, _perfil_do_job(job))
    return pipeline.executar_job(con, job.id, passos, cfg.work_dir)


def cmd_run(args) -> int:
    con = _con(args)
    try:
        cfg = config.carregar()
        job = (db.obter_job(con, args.job) if args.job
               else db.proximo_job(con, PENDENTES))
        if job is None:
            print("nada a fazer")
            return 0
        final = _avancar(con, cfg, job)
        print(f"job #{job.id} terminou em {final}")
        return 0 if final != e.ERRO else 1
    finally:
        con.close()


def cmd_canais(args) -> int:
    from vidbot import canais

    con = _con(args)
    try:
        if args.acao == "add":
            try:
                cid = canais.cadastrar(con, args.url, args.perfil)
            except ValueError as erro:
                print(erro)
                return 1
            print(f"canal #{cid} monitorado com o perfil {args.perfil}")
            return 0
        if args.acao in {"on", "off"}:
            ok = canais.definir_ativo(con, args.id, args.acao == "on")
            print(f"canal #{args.id} {'ativado' if args.acao == 'on' else 'pausado'}"
                  if ok else f"canal #{args.id} nao existe")
            return 0 if ok else 1
        if args.acao == "rm":
            ok = canais.remover(con, args.id)
            print(f"canal #{args.id} removido" if ok else f"canal #{args.id} nao existe")
            return 0 if ok else 1

        registrados = canais.listar(con)
        if not registrados:
            print("nenhum canal monitorado — use: canais add <url|@handle> -p <perfil>")
            return 0
        for c in registrados:
            marca = "ativo " if c.ativo else "pausado"
            visto = c.visto_em or "nunca"
            print(f"#{c.id:>3} {marca} {c.perfil:<12} {c.nome:<24} visto: {visto}")
        return 0
    finally:
        con.close()


def cmd_descobrir(args) -> int:
    """Passo 2 da fabrica: procura videos novos nos canais monitorados."""
    from vidbot import canais

    con = _con(args)
    try:
        novos = canais.descobrir(con, limite=args.limite)
        if not novos:
            print("nenhum video novo")
            return 0
        for job in novos:
            print(f"job #{job.id} criado: {job.titulo or job.video_id} ({job.perfil})")
        return 0
    finally:
        con.close()


def cmd_ciclo(args) -> int:
    """A fabrica inteira, para pendurar no cron.

    descobrir videos novos -> avancar todos os jobs pendentes -> subir a fila.
    """
    from vidbot import canais

    con = _con(args)
    try:
        cfg = config.carregar()
        novos = canais.descobrir(con, limite=args.limite)
        print(f"descoberta: {len(novos)} video(s) novo(s)")

        # O teto evita laco infinito se um job voltar pendente por um bug.
        for _ in range(args.max_jobs):
            job = db.proximo_job(con, PENDENTES)
            if job is None:
                break
            final = _avancar(con, cfg, job)
            print(f"job #{job.id}: {final}")
        else:
            print(f"parei em {args.max_jobs} jobs neste ciclo")
        return cmd_publicar(args)
    finally:
        con.close()


def _db_path(args) -> Path:
    return Path(args.db) if args.db else config.carregar().db_path


def cmd_bot(args) -> int:
    """Sobe o bot do Telegram (polling) para aprovar e publicar cortes."""
    from vidbot import bot

    cfg = config.carregar()
    if not cfg.telegram_token:
        print("TELEGRAM_BOT_TOKEN nao configurado no .env")
        return 1
    if not cfg.telegram_ids:
        print("TELEGRAM_ALLOWED_USER_IDS nao configurado no .env — ninguem poderia usar o bot")
        return 1
    caminho = _db_path(args)
    con = db.conectar(caminho)
    try:
        app = bot.criar_app(cfg, con, caminho)
        print("bot no ar — /cortes lista os pendentes de aprovacao")
        app.run_polling()
        return 0
    finally:
        con.close()


def cmd_publicar(args) -> int:
    """Drena a fila de cortes aprovados que ainda nao subiram.

    E o que torna verdadeira a promessa do bot quando a cota do dia acaba:
    sem isto, todo corte aprovado depois do limite diario ficaria parado
    para sempre.
    """
    from vidbot import bot, etapas, perfis as mod_perfis, youtube as yt

    con = _con(args)
    try:
        cfg = config.carregar()
        fila = db.listar_cortes_aprovados(con)
        if not fila:
            print("nenhum corte aprovado esperando upload")
            return 0
        todos = (mod_perfis.carregar_todos(_perfis_dir())
                 if _perfis_dir().is_dir() else {})
        tokens_dir = config.RAIZ / "tokens"
        for posicao, corte in enumerate(fila):
            if not yt.tem_quota(con, yt.hoje()):
                print(f"cota do dia esgotada — {len(fila) - posicao} corte(s) ficam para amanha")
                break
            job = db.obter_job(con, corte.job_id)
            perfil = todos.get(job.perfil) or etapas.PERFIL_PADRAO
            servico = yt.servico_do_perfil(perfil, tokens_dir)
            resultado = bot.publicar_ou_avisar(
                con, corte, perfil, yt.meta_do_job(cfg, job), servico)
            print(f"corte #{corte.id}: {resultado}")
        return 0
    finally:
        con.close()


def cmd_autorizar(args) -> int:
    """Gera o token OAuth do canal de um perfil (roda uma vez por canal)."""
    from vidbot import perfis as mod_perfis, youtube as yt

    todos = mod_perfis.carregar_todos(_perfis_dir()) if _perfis_dir().is_dir() else {}
    perfil = todos.get(args.perfil)
    if perfil is None:
        print(f"perfil '{args.perfil}' nao encontrado em {_perfis_dir()}")
        return 1

    destino = yt.caminho_do_token(perfil, config.RAIZ / "tokens")
    if destino is None:
        print(f"o perfil '{args.perfil}' nao declara canal_token no YAML — "
              f"defina, por exemplo, canal_token: {args.perfil}.json")
        return 1
    if destino.exists() and not args.forcar:
        print(f"{destino} ja existe — use --forcar para autorizar de novo")
        return 0

    segredos = Path(args.client_secrets)
    if not segredos.is_file():
        print(f"nao achei o client_secrets em {segredos}\n"
              "Baixe em console.cloud.google.com > APIs e Servicos > Credenciais\n"
              "(tipo 'App para computador', com a YouTube Data API v3 ativada).")
        return 1

    print("Vou abrir o navegador para voce entrar na conta do canal.\n"
          "Sem tela nesta maquina? Rode este comando no seu computador e copie\n"
          f"o arquivo gerado para {destino}.\n")
    try:
        yt.autorizar(segredos, destino, porta=args.porta)
    except Exception as erro:  # noqa: BLE001 - a mensagem do Google e o que importa
        print(f"autorizacao falhou: {erro}")
        return 1
    print(f"token salvo em {destino} — o canal '{args.perfil}' ja pode publicar")
    return 0


def cmd_limpar(args) -> int:
    """Remove workdirs de jobs que ja terminaram."""
    import shutil

    con = _con(args)
    try:
        cfg = config.carregar()
        finais = ",".join("?" * len(e.JOB_FINAIS))
        ids = [r["id"] for r in con.execute(
            f"SELECT id FROM jobs WHERE estado IN ({finais})", list(e.JOB_FINAIS))]
        removidos = 0
        for job_id in ids:
            d = Path(cfg.work_dir) / str(job_id)
            if d.is_dir():
                shutil.rmtree(d)
                removidos += 1
        print(f"{removidos} workdir(s) removido(s)")
        return 0
    finally:
        con.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="vidbot")
    parser.add_argument("--db", help="caminho do SQLite (padrao: .env)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="confere dependencias e credenciais")
    sub.add_parser("jobs", help="lista os jobs recentes")

    p_in = sub.add_parser("ingest", help="cria um job a partir de um link")
    p_in.add_argument("url")
    p_in.add_argument("-p", "--perfil", required=True)

    p_run = sub.add_parser("run", help="avanca um job ate onde der")
    p_run.add_argument("--job", type=int, help="id; sem isso pega o proximo")

    sub.add_parser("limpar", help="apaga workdirs de jobs encerrados")
    sub.add_parser("bot", help="sobe o bot do Telegram para aprovar/publicar cortes")
    sub.add_parser("publicar", help="sobe os cortes aprovados que ficaram sem cota")

    p_can = sub.add_parser("canais", help="cadastra e lista os canais monitorados")
    can_sub = p_can.add_subparsers(dest="acao")
    p_add = can_sub.add_parser("add", help="passa a monitorar um canal")
    p_add.add_argument("url", help="@handle ou link do canal")
    p_add.add_argument("-p", "--perfil", required=True)
    for acao, ajuda in (("rm", "para de monitorar"), ("on", "retoma"), ("off", "pausa")):
        p_a = can_sub.add_parser(acao, help=ajuda)
        p_a.add_argument("id", type=int)

    p_aut = sub.add_parser(
        "autorizar", help="gera o token do YouTube para o canal de um perfil")
    p_aut.add_argument("perfil")
    p_aut.add_argument("--client-secrets", default="client_secrets.json",
                       dest="client_secrets", help="json baixado do Google Cloud")
    p_aut.add_argument("--porta", type=int, default=0,
                       help="porta local do retorno OAuth (0 = qualquer livre)")
    p_aut.add_argument("--forcar", action="store_true",
                       help="reautoriza mesmo que ja exista token")

    p_desc = sub.add_parser("descobrir", help="procura videos novos nos canais")
    p_desc.add_argument("--limite", type=int, default=10,
                        help="quantos uploads recentes olhar por canal")

    p_ciclo = sub.add_parser(
        "ciclo", help="descobre, processa e publica — o comando para o cron")
    p_ciclo.add_argument("--limite", type=int, default=10)
    p_ciclo.add_argument("--max-jobs", type=int, default=20, dest="max_jobs",
                         help="teto de jobs processados neste ciclo")

    args = parser.parse_args(argv)
    return {
        "doctor": cmd_doctor, "ingest": cmd_ingest, "jobs": cmd_jobs,
        "run": cmd_run, "limpar": cmd_limpar, "bot": cmd_bot,
        "publicar": cmd_publicar, "canais": cmd_canais,
        "descobrir": cmd_descobrir, "ciclo": cmd_ciclo,
        "autorizar": cmd_autorizar,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
