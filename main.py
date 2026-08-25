"""CLI da fabrica de cortes. Nucleo puro: nao sabe quem o chamou."""
from __future__ import annotations

import argparse
import sys

from vidbot import config


def cmd_doctor(_args) -> int:
    cfg = config.carregar()
    problemas = 0
    for nome, ok, detalhe in config.diagnosticar(cfg):
        print(f"{'OK  ' if ok else 'FALTA'} {nome}: {detalhe}")
        problemas += 0 if ok else 1
    print("\ntudo pronto" if not problemas else f"\n{problemas} pendencia(s)")
    return 0 if not problemas else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="vidbot")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="confere dependencias e credenciais")
    args = parser.parse_args(argv)
    return {"doctor": cmd_doctor}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
