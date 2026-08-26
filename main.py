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


def cmd_run(args) -> int:
    from vidbot import etapas, perfis as mod_perfis

    con = _con(args)
    try:
        cfg = config.carregar()
        job = (db.obter_job(con, args.job) if args.job
               else db.proximo_job(con, [e.NOVO, e.LEGENDA_OBTIDA, e.SEGMENTADO]))
        if job is None:
            print("nada a fazer")
            return 0
        todos = mod_perfis.carregar_todos(Path("perfis"))
        perfil = todos.get(job.perfil) or etapas.PERFIL_PADRAO
        passos = etapas.montar(con, cfg, perfil)
        final = pipeline.executar_job(con, job.id, passos, cfg.work_dir)
        print(f"job #{job.id} terminou em {final}")
        return 0 if final != e.ERRO else 1
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
        todos = mod_perfis.carregar_todos(config.RAIZ / "perfis")
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

    args = parser.parse_args(argv)
    return {
        "doctor": cmd_doctor, "ingest": cmd_ingest, "jobs": cmd_jobs,
        "run": cmd_run, "limpar": cmd_limpar, "bot": cmd_bot,
        "publicar": cmd_publicar,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
