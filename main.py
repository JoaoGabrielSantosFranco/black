"""CLI da fabrica de cortes. Nucleo puro: nao sabe quem o chamou."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from vidbot import config, db, estados as e, pipeline
from vidbot.urls import extrair_video_id


def montar_passos() -> dict[str, pipeline.Passo]:
    """Etapas reais do pipeline. Preenchido pelas tarefas 5 em diante."""
    return {}


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
    con = _con(args)
    try:
        cfg = config.carregar()
        passos = montar_passos()
        pendentes = [s for s in passos] or [e.NOVO]
        job = (db.obter_job(con, args.job) if args.job
               else db.proximo_job(con, pendentes))
        if job is None:
            print("nada a fazer")
            return 0
        final = pipeline.executar_job(con, job.id, passos, cfg.work_dir)
        print(f"job #{job.id} terminou em {final}")
        return 0 if final != e.ERRO else 1
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

    args = parser.parse_args(argv)
    return {
        "doctor": cmd_doctor, "ingest": cmd_ingest,
        "jobs": cmd_jobs, "run": cmd_run,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
