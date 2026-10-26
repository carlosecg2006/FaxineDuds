"""Comando: python -m faxineiro converter ARQUIVO --para FORMATO [--substituir] [--so-previa]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import cli_quarentena
from .config import CAMINHO_INDICE, PASTA_TESTE
from .conversor import ConversaoRecusada, converter, formatos_possiveis, localizar_ffmpeg, planejar_conversao
from .formato import formatar_bytes, formatar_duracao, relativo
from .indice import Indice
from .quarentena import Quarentena


def cmd_converter(args: argparse.Namespace) -> int:
    arquivo = Path(args.arquivo)
    ferramentas = localizar_ffmpeg()
    if args.formatos or not args.para:
        opcoes = formatos_possiveis(arquivo, ferramentas) if arquivo.is_file() else []
        if not opcoes:
            print("Não sei converter este arquivo (por enquanto: imagens, áudio e vídeo).")
            return 1
        print(f"Formatos para {arquivo.name}:")
        for o in opcoes:
            print(f"  {o.formato:<6} {o.rotulo}" + ("" if o.disponivel else f"  — indisponível: {o.motivo}"))
        return 0

    try:
        plano = planejar_conversao(arquivo, args.para, modo="substituir" if args.substituir else "novo",
                                   ferramentas=ferramentas)
    except ConversaoRecusada as erro:
        print(f"Recusado: {erro}", file=sys.stderr)
        return 2
    print("== Prévia da conversão ".ljust(60, "="))
    print(f"  de:   {relativo(plano.origem, PASTA_TESTE)} ({formatar_bytes(plano.origem.stat().st_size)})")
    print(f"  para: {relativo(plano.destino, PASTA_TESTE)}" + ("  (nome trocado: já existe um igual)" if plano.renomeado else ""))
    print(f"  como: {plano.como}")
    if plano.duracao:
        print(f"  duração: {formatar_duracao(plano.duracao)}")
    print("  original: " + ("vai para a QUARENTENA depois de conferir a conversão (dá para desfazer)"
                            if plano.modo == "substituir" else "fica intacto"))
    if args.so_previa:
        print("(só prévia: nada foi feito)")
        return 0
    if not cli_quarentena._confirmar("Converter?", args):
        print("Cancelado. Nada foi feito.")
        return 0

    with Indice(args.indice) as indice, cli_quarentena_ctrl_c() as ctrl:
        q = Quarentena(indice, limite=PASTA_TESTE)
        r = converter(plano, indice=indice, quarentena=q, parar=lambda: ctrl.pedido, ferramentas=ferramentas,
                      ao_progredir=lambda f: print(f"\rConvertendo... {f * 100:5.1f}%", end="", flush=True))
    print()
    if r.cancelado:
        print("Cancelado: nenhum arquivo foi criado e o original está intacto.")
        return 0
    print(f"Pronto em {r.segundos:.1f} s: {relativo(r.destino, PASTA_TESTE)} ({formatar_bytes(r.destino.stat().st_size)})")
    if r.lote_id:
        print(f"Original na quarentena (lote {r.lote_id}). Para desfazer: python -m faxineiro quarentena desfazer --lote {r.lote_id}")
    if r.aviso:
        print(f"  aviso: {r.aviso}")
    return 0


def cli_quarentena_ctrl_c():
    from .cli_ia import _CtrlC

    return _CtrlC()


def registrar(sub: argparse._SubParsersAction) -> None:
    c = sub.add_parser("converter", help="converte imagem, áudio ou vídeo (com prévia)")
    c.add_argument("arquivo")
    c.add_argument("--para", help="formato de destino (ex.: jpg, mp3, mp4, audio)")
    c.add_argument("--formatos", action="store_true", help="só lista para quais formatos dá para converter")
    c.add_argument("--substituir", action="store_true",
                   help="depois de conferir, manda o original para a quarentena (dá para desfazer)")
    c.add_argument("--so-previa", action="store_true")
    c.add_argument("--sim", action="store_true", help="não pergunta (a prévia aparece mesmo assim)")
    c.add_argument("--indice", default=str(CAMINHO_INDICE), help=argparse.SUPPRESS)
    c.set_defaults(func=cmd_converter)
