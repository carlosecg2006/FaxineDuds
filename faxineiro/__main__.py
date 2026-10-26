"""Linha de comando: python -m faxineiro escanear|raiox|quarentena ..."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import raiox
from .config import (
    CAMINHO_INDICE,
    MB,
    PASTA_TESTE,
    PESADO_MINIMO,
    PESADO_MINIMO_TESTE,
    TOP_PESADOS,
    dentro_da_pasta_teste,
)
from . import cli_ia, cli_quarentena
from .formato import formatar_bytes
from .formato import numero as _numero
from .formato import relativo as _relativo
from .hashes import Hasher
from .indice import Indice
from .scanner import Progresso, escanear


def _pasta_permitida(pasta: Path) -> int | None:
    """Trava da pasta_teste (regra 5). Devolve código de erro ou None se pode seguir."""
    if not dentro_da_pasta_teste(pasta):
        print(f"Recusado: durante o desenvolvimento só posso trabalhar em {PASTA_TESTE}.", file=sys.stderr)
        return 2
    if not pasta.is_dir():
        print(f"Pasta não encontrada: {pasta}", file=sys.stderr)
        return 1
    return None


# --- escanear --------------------------------------------------------------


def _mostrar_progresso(p: Progresso) -> None:
    linha = (f"Varridos {_numero(p.varridos)} | novos {_numero(p.novos)} | "
             f"alterados {_numero(p.alterados)} | iguais {_numero(p.iguais)} | "
             f"ignorados {_numero(p.ignorados)} | erros {_numero(p.erros)}")
    print("\r" + linha, end="", flush=True)


def cmd_escanear(args: argparse.Namespace) -> int:
    pasta = Path(args.pasta)
    if (erro := _pasta_permitida(pasta)) is not None:
        return erro

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


# --- raio-x ----------------------------------------------------------------


def _titulo(texto: str) -> None:
    print()
    print(f"== {texto} ".ljust(60, "="))


def minimo_pesado(args: argparse.Namespace) -> int:
    """--minimo-mb vence; senão --teste usa o mínimo pequeno; senão o padrão (100 MB)."""
    if args.minimo_mb is not None:
        return int(args.minimo_mb * MB)
    return PESADO_MINIMO_TESTE if args.teste else PESADO_MINIMO


def cmd_raiox(args: argparse.Namespace) -> int:
    pasta = Path(args.pasta)
    if (erro := _pasta_permitida(pasta)) is not None:
        return erro
    base = pasta.resolve()

    with Indice(args.indice) as indice:
        if not indice.foi_escaneada(str(base)):
            print(f"Esta pasta ainda não foi escaneada. Rode antes: python -m faxineiro escanear", file=sys.stderr)
            return 1

        hasher = Hasher()

        def progresso(p: raiox.ProgressoHash) -> None:
            print(f"\rCalculando hashes: {p.feitos}/{p.total} arquivos, "
                  f"{formatar_bytes(p.bytes_lidos)} lidos", end="", flush=True)

        dup = raiox.encontrar_duplicados(indice, base, hasher=hasher, ao_progredir=progresso)
        print()
        print(f"Hashes calculados agora: {hasher.parciais} parciais, {hasher.completos} completos "
              f"(o resto veio do índice)")
        lx = raiox.lixo(indice, base)
        errados = raiox.extensao_errada(indice, base)
        vazias = raiox.pastas_vazias(base)
        minimo = minimo_pesado(args)
        grandes = raiox.pesados(indice, base, args.top, minimo)
        categorias = raiox.totais_por_categoria(indice, base)

        _titulo("Resumo")
        total = dup.recuperavel + lx.recuperavel
        print(f"Dá para liberar {formatar_bytes(total)} "
              f"(duplicados {formatar_bytes(dup.recuperavel)} + temporários {formatar_bytes(lx.recuperavel)})")
        print(f"{len(dup.grupos)} grupos de duplicados | {len(lx.temporarios)} temporários | "
              f"{len(lx.vazios)} arquivos vazios | {len(vazias)} pastas vazias | "
              f"{len(errados)} com extensão errada")

        _titulo("Duplicados")
        if not dup.grupos:
            print("Nenhum duplicado encontrado.")
        for i, g in enumerate(dup.grupos, 1):
            print(f"Grupo {i}: {len(g.arquivos)} cópias, libera {formatar_bytes(g.recuperavel)}")
            print(f"  motivo: {g.motivo}")
            for a in g.arquivos:
                marca = "manter →" if a["id"] == g.manter["id"] else "        "
                print(f"  {marca} {_relativo(a['caminho'], base)}  (criado {a['criado_em']})")
        for c in dup.desatualizados:
            print(f"  aviso: {_relativo(c, base)} mudou desde a última varredura; rode `escanear` de novo")
        for e in dup.erros:
            print(f"  erro: {e}")

        _titulo(f"Pesados (a partir de {formatar_bytes(minimo)}, top {args.top})")
        if not grandes:
            print(f"  Nenhum arquivo com {formatar_bytes(minimo)} ou mais.")
        for a in grandes:
            print(f"  {formatar_bytes(a['tamanho']):>10}  {_relativo(a['caminho'], base)}")
        print("  Por categoria:")
        for c in categorias:
            print(f"  {c['categoria']:<12} {c['quantidade']:>6} arquivos  {formatar_bytes(c['bytes'] or 0):>10}")

        _titulo("Lixo")
        for a in lx.temporarios:
            print(f"  temporário: {_relativo(a['caminho'], base)} ({formatar_bytes(a['tamanho'])})")
        for a in lx.vazios:
            print(f"  vazio:      {_relativo(a['caminho'], base)}")
        for p in vazias:
            print(f"  pasta vazia: {_relativo(p, base)}")
        if not (lx.temporarios or lx.vazios or vazias):
            print("Nada encontrado.")

        _titulo("Extensão errada (suspeito, não é lixo)")
        for a in errados:
            print(f"  {_relativo(a['caminho'], base)}: o conteúdo é {a['tipo_real']}")
        if not errados:
            print("Nada encontrado.")

        print()
        print("O Raio-X só mostra. Nada foi movido nem apagado.")
    return 0


def _saida_em_utf8() -> None:
    """No Windows, saída redirecionada (arquivo/pipe) usa cp1252 e quebra com "→" e "…"."""
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _saida_em_utf8()
    parser = argparse.ArgumentParser(prog="faxineiro")
    sub = parser.add_subparsers(dest="comando", required=True)

    esc = sub.add_parser("escanear", help="varre uma pasta e atualiza o índice")
    esc.add_argument("pasta", nargs="?", default=str(PASTA_TESTE))
    esc.add_argument("--indice", default=str(CAMINHO_INDICE), help=argparse.SUPPRESS)
    esc.set_defaults(func=cmd_escanear)

    rx = sub.add_parser("raiox", help="mostra duplicados, arquivos pesados e lixo")
    rx.add_argument("pasta", nargs="?", default=str(PASTA_TESTE))
    rx.add_argument("--top", type=int, default=TOP_PESADOS, help="quantos arquivos pesados mostrar")
    rx.add_argument("--minimo-mb", type=float, default=None,
                    help=f"tamanho mínimo de um arquivo pesado, em MB (padrão {PESADO_MINIMO // MB})")
    rx.add_argument("--teste", action="store_true",
                    help=f"modo de teste: mínimo de {PESADO_MINIMO_TESTE // MB} MB para a pasta_teste")
    rx.add_argument("--indice", default=str(CAMINHO_INDICE), help=argparse.SUPPRESS)
    rx.set_defaults(func=cmd_raiox)

    cli_quarentena.registrar(sub)
    cli_ia.registrar(sub)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
