"""Comandos da quarentena: mover, duplicados, listar, desfazer, esvaziar; e mover-unidade (Fase 7B).

Todos mostram a prévia (dry-run) primeiro e só executam depois da confirmação.
Sem `--pc-real`, só mexem na pasta_teste. Com `--pc-real`, pedem para digitar PC REAL.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from . import config
from .config import CAMINHO_INDICE, PASTA_TESTE, dentro_da_pasta_teste
from .formato import formatar_bytes, ha_quanto_tempo, relativo
from .indice import Indice
from .quarentena import Plano, Quarentena, Resultado

CONFIRMACAO_PC_REAL = "PC REAL"


def _perguntar(texto: str) -> str:
    try:
        return input(texto).strip()
    except EOFError:  # sem teclado (ex.: rodando por script): vale como "não"
        return ""


def _confirmar(texto: str, args: argparse.Namespace) -> bool:
    if getattr(args, "sim", False):
        return True
    return _perguntar(f"{texto} (s/n): ").lower() in ("s", "sim")


def ligar_pc_real(args: argparse.Namespace) -> bool:
    """Modo PC real (Fase 7B): só liga digitando PC REAL. Vale só para este comando."""
    if not getattr(args, "pc_real", False):
        return False
    areas = ", ".join(str(a) for a in config.AREAS_DE_LEITURA)
    print(f"MODO PC REAL: esta ação pode mexer em {areas} (fora da pasta_teste).")
    print("Pastas bloqueadas, pastas-bloco, de programa, da nuvem e backups continuam proibidas.")
    if _perguntar(f"Digite {CONFIRMACAO_PC_REAL} para ligar: ") != CONFIRMACAO_PC_REAL:
        raise SystemExit("Modo PC real NÃO foi ligado. Nada foi feito.")
    return True


def areas(args: argparse.Namespace) -> tuple:
    return config.areas_de_acao(True) if args.pc_real_ligado else (PASTA_TESTE,)


def _abrir(args: argparse.Namespace) -> tuple[Indice, Quarentena]:
    if not hasattr(args, "pc_real_ligado"):
        args.pc_real_ligado = ligar_pc_real(args)
    indice = Indice(args.indice)
    q = Quarentena(indice, limite=areas(args))
    for msg in q.recuperar_diario():
        print(f"[diário] {msg}")
    return indice, q


def _mostrar_plano(plano: Plano, titulo: str) -> None:
    print(f"== Prévia: {titulo} ".ljust(60, "="))
    for i, p in enumerate(plano.passos, 1):
        origem = relativo(p.origem, PASTA_TESTE)
        if p.problema:
            print(f"  {i:>3}. PULA  {origem}  — {p.problema}")
            continue
        if p.remover_pasta:
            print(f"  {i:>3}. remove a pasta (se ficar vazia; o desfazer recria) {origem}")
        elif plano.tipo == "mover_unidade":
            nota = "  (nome trocado: já existe um igual)" if p.renomeado else ""
            print(f"  {i:>3}. {origem}  →  {p.destino}  ({formatar_bytes(p.tamanho)}){nota}")
        elif p.quarentenar_copia:
            print(f"  {i:>3}. a cópia {origem} vai para a quarentena da unidade dela")
        elif plano.tipo == "esvaziar":
            print(f"  {i:>3}. APAGA {origem}  ({formatar_bytes(p.tamanho)})")
        elif plano.tipo == "restaurar":
            nota = "  (com outro nome: já existe um arquivo lá)" if p.renomeado else ""
            print(f"  {i:>3}. volta para {relativo(p.destino, PASTA_TESTE)}{nota}")
        else:
            mantem = f"  (fica: {relativo(p.manter, PASTA_TESTE)})" if p.manter else ""
            print(f"  {i:>3}. {origem}  ({formatar_bytes(p.tamanho)}){mantem}")
    print(f"Total: {len(plano.validos)} item(ns), {formatar_bytes(plano.total_bytes)}")
    for aviso in plano.avisos:
        print(f"  ! {aviso}")


def _mostrar_resultado(r: Resultado, verbo: str) -> None:
    if r.lote_id is not None:
        print(f"Lote {r.lote_id}: {len(r.feitos)} {verbo}, {len(r.falhas)} com problema.")
    for passo, msg in r.falhas:
        print(f"  problema: {relativo(passo.origem, PASTA_TESTE)}: {msg}")


def _rodar(args: argparse.Namespace, montar: Callable[[Quarentena], Plano], titulo: str, verbo: str) -> int:
    indice, q = _abrir(args)
    try:
        plano = montar(q)
        _mostrar_plano(plano, titulo)
        if not plano.validos:
            print("Nada a fazer.")
            return 0
        if args.so_previa:
            print("(só prévia: nada foi feito)")
            return 0
        if not _confirmar("Confirmar?", args):
            print("Cancelado. Nada foi feito.")
            return 0
        r = q.executar(plano)
        _mostrar_resultado(r, verbo)
        return 0 if not r.falhas else 1
    finally:
        indice.fechar()


# --- comandos ------------------------------------------------------------------


def cmd_mover(args: argparse.Namespace) -> int:
    return _rodar(args, lambda q: q.planejar_mover(args.arquivos),
                  "mandar para a quarentena", "na quarentena")


def cmd_mover_unidade(args: argparse.Namespace) -> int:
    from .transferir import planejar_mover_unidade

    return _rodar(args, lambda q: planejar_mover_unidade(q, args.itens, args.para),
                  f"mover para outra unidade ({args.para})", "movidos com hash conferido")


def cmd_duplicados(args: argparse.Namespace) -> int:
    pasta = Path(args.pasta)
    if not dentro_da_pasta_teste(pasta):
        print(f"Recusado: durante o desenvolvimento só posso trabalhar em {PASTA_TESTE}.", file=sys.stderr)
        return 2
    return _rodar(args, lambda q: q.planejar_duplicados(pasta),
                  "duplicados do Raio-X para a quarentena (fica o sugerido)", "na quarentena")


def cmd_desfazer(args: argparse.Namespace) -> int:
    def conflito(original: Path) -> str:
        if args.conflito != "perguntar":
            return args.conflito
        resp = _perguntar(f"Já existe {relativo(original, PASTA_TESTE)}. [r]enomear o restaurado ou [p]ular? ")
        return "renomear" if resp.lower().startswith("r") else "pular"

    return _rodar(args, lambda q: q.planejar_desfazer(item=args.item, lote=args.lote, conflito=conflito),
                  "desfazer (trazer de volta)", "restaurados com hash conferido")


def cmd_listar(args: argparse.Namespace) -> int:
    indice, _ = _abrir(args)
    try:
        itens = indice.itens_na_quarentena()
        if not itens:
            print("A quarentena está vazia.")
            return 0
        print(f"{'item':>5} {'lote':>5}  {'tamanho':>10}  {'desde':<12}  de onde veio")
        por_unidade: dict[str, int] = {}
        for op in itens:
            onde = str(config.pasta_quarentena(op["origem"]))
            por_unidade[onde] = por_unidade.get(onde, 0) + (op["tamanho"] or 0)
        for op in itens:
            print(f"{op['id']:>5} {op['lote_id']:>5}  {formatar_bytes(op['tamanho'] or 0):>10}  "
                  f"{ha_quanto_tempo(op['concluido_em']):<12}  {relativo(op['origem'], PASTA_TESTE)}")
        print()
        print("Por lote:")
        for lote in indice.lotes_na_quarentena():
            print(f"  Lote {lote['lote_id']}: {lote['quantidade']} arquivo(s), "
                  f"{formatar_bytes(lote['bytes'] or 0)}, na quarentena {ha_quanto_tempo(lote['desde'])} "
                  f"(desde {lote['desde'][:10]})")
        total = sum(op["tamanho"] or 0 for op in itens)
        print(f"Espaço total ocupado pela quarentena: {formatar_bytes(total)} em {len(itens)} arquivo(s)")
        for onde, bytes_ in sorted(por_unidade.items()):
            print(f"  {onde}: {formatar_bytes(bytes_)}")
        return 0
    finally:
        indice.fechar()


def cmd_esvaziar(args: argparse.Namespace) -> int:
    indice, q = _abrir(args)
    try:
        plano = q.planejar_esvaziar(args.unidade)
        onde = f" DO {args.unidade.upper()}" if args.unidade else " (TODAS AS UNIDADES)"
        _mostrar_plano(plano, f"ESVAZIAR A QUARENTENA{onde} (apaga de vez, sem volta)")
        if not plano.validos:
            print("Nada a apagar.")
            return 0
        if args.so_previa:
            print("(só prévia: nada foi apagado)")
            return 0
        espaco = formatar_bytes(plano.total_bytes)
        print(f"Isto vai liberar {espaco} e NÃO DÁ PARA DESFAZER.")
        if _perguntar("1/2 — Tem certeza? (s/n): ").lower() not in ("s", "sim"):
            print("Cancelado. Nada foi apagado.")
            return 0
        if _perguntar("2/2 — Digite ESVAZIAR para confirmar: ") != "ESVAZIAR":
            print("Cancelado. Nada foi apagado.")
            return 0
        r = q.executar(plano)
        liberado = sum(p.tamanho for p in r.feitos)
        _mostrar_resultado(r, "apagados")
        print(f"Liberado: {formatar_bytes(liberado)}")
        return 0 if not r.falhas else 1
    finally:
        indice.fechar()


def registrar(sub: argparse._SubParsersAction) -> None:
    q = sub.add_parser("quarentena", help="excluir com segurança, desfazer e esvaziar")
    qsub = q.add_subparsers(dest="acao", required=True)

    def comum(p: argparse.ArgumentParser, com_sim: bool = True) -> None:
        p.add_argument("--so-previa", action="store_true", help="só mostra o que seria feito")
        p.add_argument("--pc-real", action="store_true",
                       help="liga o modo PC real (pede para digitar PC REAL): mexe fora da pasta_teste")
        if com_sim:
            p.add_argument("--sim", action="store_true", help="não pergunta (a prévia aparece mesmo assim)")
        p.add_argument("--indice", default=str(CAMINHO_INDICE), help=argparse.SUPPRESS)

    m = qsub.add_parser("mover", help="manda arquivos (ou pastas inteiras) para a quarentena")
    m.add_argument("arquivos", nargs="+", help="arquivos e/ou pastas")
    comum(m)
    m.set_defaults(func=cmd_mover)

    d = qsub.add_parser("duplicados", help="manda os duplicados do Raio-X, mantendo o sugerido")
    d.add_argument("pasta", nargs="?", default=str(PASTA_TESTE))
    comum(d)
    d.set_defaults(func=cmd_duplicados)

    l = qsub.add_parser("listar", help="mostra o que está na quarentena")
    l.add_argument("--indice", default=str(CAMINHO_INDICE), help=argparse.SUPPRESS)
    l.set_defaults(func=cmd_listar)

    u = qsub.add_parser("desfazer", help="traz de volta um item ou um lote")
    alvo = u.add_mutually_exclusive_group(required=True)
    alvo.add_argument("--item", type=int)
    alvo.add_argument("--lote", type=int)
    u.add_argument("--conflito", choices=["perguntar", "renomear", "pular"], default="perguntar",
                   help="se já existir arquivo com o mesmo nome (nunca sobrescreve)")
    comum(u)
    u.set_defaults(func=cmd_desfazer)

    e = qsub.add_parser("esvaziar", help="APAGA DE VEZ o que está na quarentena (confirmação dupla)")
    e.add_argument("--unidade", help="só a quarentena desta unidade, ex.: D: (sem isto: todas)")
    comum(e, com_sim=False)
    e.set_defaults(func=cmd_esvaziar)

    mu = sub.add_parser("mover-unidade", help="move arquivos/pastas para OUTRA unidade (cópia conferida por hash)")
    mu.add_argument("itens", nargs="+", help="arquivos e/ou pastas")
    mu.add_argument("--para", required=True, help="pasta de destino, em outra unidade")
    comum(mu)
    mu.set_defaults(func=cmd_mover_unidade)
