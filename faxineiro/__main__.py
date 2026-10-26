"""Linha de comando: python -m faxineiro escanear [pasta]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import CAMINHO_INDICE, PASTA_TESTE, dentro_da_pasta_teste
from .indice import Indice
from .scanner import Progresso, escanear


def formatar_bytes(n: int) -> str:
    for unidade in ("B", "KB", "MB", "GB"):
        if n < 1024 or unidade == "GB":
            return f"{n:.0f} {unidade}" if unidade == "B" else f"{n:.1f} {unidade}"
        n /= 1024
    return f"{n} B"


def _numero(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _mostrar_progresso(p: Progresso) -> None:
    linha = (f"Varridos {_numero(p.varridos)} | novos {_numero(p.novos)} | "
             f"alterados {_numero(p.alterados)} | iguais {_numero(p.iguais)} | "
             f"ignorados {_numero(p.ignorados)} | erros {_numero(p.erros)}")
    print("\r" + linha, end="", flush=True)


def cmd_escanear(args: argparse.Namespace) -> int:
    pasta = Path(args.pasta)
    if not dentro_da_pasta_teste(pasta):
        print(f"Recusado: durante o desenvolvimento só posso varrer {PASTA_TESTE}.", file=sys.stderr)
        return 2
    if not pasta.is_dir():
        print(f"Pasta não encontrada: {pasta}", file=sys.stderr)
        return 1

    with Indice(args.indice) as indice:
        p = escanear(pasta, indice, ao_progredir=_mostrar_progresso)
        print()
        print(f"Removidos do índice (sumiram da pasta): {_numero(p.removidos)}")
        for ignorada in p.pastas_ignoradas:
            print(f"  ignorada (bloqueada): {ignorada}")
        for aviso in p.avisos:
            print(f"  aviso: {aviso}")
        print(f"Arquivos no índice: {_numero(indice.contar())}")
        indice.checkpoint()
        print(f"Índice: {formatar_bytes(indice.tamanho_em_disco())} ({indice.caminho})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="faxineiro")
    sub = parser.add_subparsers(dest="comando", required=True)
    esc = sub.add_parser("escanear", help="varre uma pasta e atualiza o índice")
    esc.add_argument("pasta", nargs="?", default=str(PASTA_TESTE))
    esc.add_argument("--indice", default=str(CAMINHO_INDICE), help=argparse.SUPPRESS)
    esc.set_defaults(func=cmd_escanear)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
