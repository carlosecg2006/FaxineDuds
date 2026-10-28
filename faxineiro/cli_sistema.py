"""Comando: python -m faxineiro sistema [--unidade C:] [--minimo-mb 50]  (Fase 7C.1, só lê)"""

from __future__ import annotations

import argparse
import sys

from . import config, sistema
from .formato import formatar_bytes, numero, relativo

SIMBOLO = {sistema.SEGURO: "[seguro limpar]", sistema.DESINSTALADOR: "[use o desinstalador]",
           sistema.NAO_MEXA: "[não mexa]"}


def _mostrar(item: sistema.Item, pai: str | None, nivel: int) -> None:
    nome = relativo(item.caminho, pai) if pai else item.caminho
    extra = "  (o Windows não deixou ler tudo)" if item.sem_permissao else ""
    print(f"{'   ' * nivel}{formatar_bytes(item.tamanho):>10}  {nome}  {SIMBOLO[item.selo]}{extra}")
    if item.explicacao:
        print(f"{'   ' * nivel}{'':>10}  {item.explicacao}")
    if item.como and item.selo != sistema.NAO_MEXA:
        print(f"{'   ' * nivel}{'':>10}  Como: {item.como}")
    for f in item.filhos:
        _mostrar(f, item.caminho, nivel + 1)


def mostrar(rx: sistema.RaioXSistema) -> None:
    print(f"== Raio-X do sistema — {rx.unidade} ".ljust(70, "="))
    for item in rx.itens:
        _mostrar(item, None, 0)
        print()
    print(f"Medido: {formatar_bytes(rx.total)} em pastas de sistema, de {formatar_bytes(rx.usado)} usados "
          f"no {rx.unidade} ({numero(rx.pastas_lidas)} pastas lidas).")
    print("Windows e WinSxS parecem maiores do que são (os mesmos arquivos vistos em dois lugares).")
    print("O Raio-X do sistema só mostra. Nada foi movido nem apagado.")


def cmd_sistema(args: argparse.Namespace) -> int:
    from .cli_ia import _CtrlC
    from .descricoes import baixar_prioridade

    baixar_prioridade()
    print(f"Medindo as pastas de sistema do {args.unidade} (só lê; Ctrl+C cancela)...", flush=True)
    with _CtrlC() as ctrl_c:
        rx = sistema.medir_sistema(
            args.unidade, parar=lambda: ctrl_c.pedido, minimo=int(args.minimo_mb * config.MB),
            ao_progredir=lambda p: print(f"\r  {numero(p.pastas)} pastas, {formatar_bytes(p.bytes)}".ljust(40),
                                         end="", flush=True))
    print()
    if rx.cancelado:
        print("Cancelado: a medição ficou pela metade e não foi guardada.", file=sys.stderr)
        return 1
    mostrar(rx)
    destino = sistema.arquivo_salvo(rx.unidade)
    sistema.salvar(rx, destino)
    print(f"Guardado em {destino} (a tela Sistema do app mostra esta medição).")
    return 0


def cmd_programas(args: argparse.Namespace) -> int:
    from . import programas

    lista = programas.listar()
    if args.ordem == "uso":  # os esquecidos primeiro: sem sinal de uso, depois o uso mais antigo
        lista.sort(key=lambda p: p.sinal_de_uso[0] or "")
    print(f"{'Tamanho':>10}  {'Último sinal de uso':<24} {'Origem':<10} Programa")
    for p in lista:
        uso, fonte = p.sinal_de_uso
        tamanho = formatar_bytes(p.tamanho) if p.tamanho is not None else "?"
        sinal = f"{fonte} {uso}" if uso else "sem sinal"
        aviso = "  (pasta não encontrada: unidade desconectada ou sobra)" if not p.pasta_existe else ""
        print(f"{tamanho:>10}  {sinal:<24} {p.origem:<10} {p.nome}{aviso}")
    print(f"\n{len(lista)} programas. Para desinstalar, use a tela Programas do app "
          "(ela chama o desinstalador oficial de cada um).")
    return 0


def cmd_limpezas(args: argparse.Namespace) -> int:
    from . import limpezas

    achados = limpezas.medir()
    for a in achados:
        print(f"{formatar_bytes(a.bytes):>10} {numero(len(a.arquivos)):>8} arquivos  {a.limpeza.titulo}"
              + (f"  — {a.motivo}" if a.motivo else ""))
    print(f"\nAté {formatar_bytes(sum(a.bytes for a in achados if a.motivo is None))} podem ir para a quarentena. "
          "Para limpar, use a tela Limpezas do app (com o modo PC real). Nada foi movido.")
    return 0


def registrar(sub) -> None:
    li = sub.add_parser("limpezas", help="quanto cada limpeza segura liberaria: temporários e caches (só lê)")
    li.set_defaults(func=cmd_limpezas)

    pr = sub.add_parser("programas", help="programas e jogos instalados: tamanho e último sinal de uso (só lê)")
    pr.add_argument("--ordem", choices=("tamanho", "uso"), default="tamanho")
    pr.set_defaults(func=cmd_programas)

    p = sub.add_parser("sistema", help="Raio-X do sistema: o que ocupa Windows, Program Files e AppData (só lê)")
    p.add_argument("--unidade", default=config.UNIDADE_DO_SISTEMA, help="unidade a medir (padrão: a do Windows)")
    p.add_argument("--minimo-mb", type=float, default=sistema.MINIMO / config.MB,
                   help="esconde pastas desconhecidas menores que isso (padrão 50)")
    p.set_defaults(func=cmd_sistema)
