"""Linha de comando: python -m faxineiro escanear|raiox|espaco|quarentena|ia|converter|gui ..."""

from __future__ import annotations

import argparse
import contextlib
import sys
import time
from datetime import datetime
from pathlib import Path

from . import cli_conversor, cli_ia, cli_quarentena, cli_sistema, raiox
from .config import (
    AREAS_DE_LEITURA,
    CAMINHO_INDICE,
    MB,
    PASTA_TESTE,
    PESADO_MINIMO,
    PESADO_MINIMO_TESTE,
    RAIZ_PROJETO,
    TOP_PESADOS,
    Bloqueios,
    bloqueios_do_pc,
    dentro_da_pasta_teste,
    pode_ler,
)
from .formato import formatar_bytes, formatar_duracao
from .formato import numero as _numero
from .formato import relativo as _relativo
from .hashes import Hasher
from .indice import Indice
from .scanner import Progresso, escanear

LIMITE_GRUPOS = 15  # no PC real podem ser milhares: mostra os que mais liberam espaço
LIMITE_LISTA = 25
LIMITE_PROGRAMAS = 12  # no "espaco": as pastas de programa maiores, o resto só somado


def _pasta_legivel(pasta: Path) -> int | None:
    """Regra 5, parte de LEITURA: escanear/analisar podem olhar a pasta_teste e as áreas do PC real."""
    if not pode_ler(pasta):
        areas = ", ".join(str(a) for a in AREAS_DE_LEITURA)
        print(f"Recusado: só posso ler {PASTA_TESTE} e {areas}.", file=sys.stderr)
        return 2
    if not pasta.is_dir():
        print(f"Pasta não encontrada: {pasta}", file=sys.stderr)
        return 1
    return None


def _bloqueios_para(pasta: Path) -> Bloqueios:
    """Na pasta_teste, os bloqueios de sempre; no PC real, também a pasta do próprio app."""
    return Bloqueios() if dentro_da_pasta_teste(pasta) else bloqueios_do_pc()


# --- escanear --------------------------------------------------------------


def _mostrar_progresso(p: Progresso) -> None:
    linha = (f"Varridos {_numero(p.varridos)} | novos {_numero(p.novos)} | "
             f"alterados {_numero(p.alterados)} | iguais {_numero(p.iguais)} | "
             f"ignorados {_numero(p.ignorados)} | erros {_numero(p.erros)}")
    print("\r" + linha, end="", flush=True)


def _escanear_uma(pasta: Path, indice: Indice, ctrl_c) -> Progresso:
    inicio = time.monotonic()
    print(f"== {pasta}")
    p = escanear(pasta, indice, bloqueios=_bloqueios_para(pasta), ao_progredir=_mostrar_progresso,
                 parar=lambda: ctrl_c.pedido)
    _mostrar_progresso(p)
    print()
    longos = [a for a in p.avisos if a.startswith("Caminho longo demais")]
    outros = [a for a in p.avisos if a not in longos]
    print(f"Tempo: {formatar_duracao(time.monotonic() - inicio)}"
          + (" — CANCELADO (nada foi removido do índice; rode de novo para continuar)" if p.cancelado else ""))
    print(f"Removidos do índice (sumiram da pasta): {_numero(p.removidos)}")
    if p.fora_por_bloqueio:
        print(f"Tirados do índice por estarem em pasta bloqueada (só as linhas do banco): {_numero(p.fora_por_bloqueio)}")
    print(f"Pastas bloqueadas puladas: {len(p.pastas_ignoradas)}"
          + (f" (ex.: {', '.join(_relativo(x, pasta) for x in p.pastas_ignoradas[:6])})" if p.pastas_ignoradas else ""))
    if longos:
        print(f"Pastas puladas por caminho longo demais (> 260 caracteres): {len(longos)}")
        for a in longos[:5]:
            print(f"  {a[:150]}")
    if outros:
        print(f"Avisos (sem permissão, em uso...): {len(outros)}")
        for a in outros[:LIMITE_LISTA if len(outros) > 8 else 8]:
            print(f"  {a[:150]}")
    return p


def cmd_escanear(args: argparse.Namespace) -> int:
    from .cli_ia import _CtrlC
    from .descricoes import baixar_prioridade

    pastas = list(AREAS_DE_LEITURA) if args.pc else [Path(args.pasta)]
    for pasta in pastas:
        if (erro := _pasta_legivel(pasta)) is not None:
            return erro
    baixar_prioridade()  # o PC continua respondendo durante a varredura
    with Indice(args.indice) as indice, _CtrlC() as ctrl_c:
        for pasta in pastas:
            p = _escanear_uma(pasta, indice, ctrl_c)
            if p.cancelado:
                break
        print(f"Arquivos no índice: {_numero(indice.contar())}")
        indice.checkpoint()
        print(f"Índice: {formatar_bytes(indice.tamanho_em_disco())} ({indice.caminho})")
    print("Só leitura: nenhum arquivo foi movido nem alterado.")
    return 0


# --- espaço (quanto do disco o índice explica) ------------------------------------


def cmd_espaco(args: argparse.Namespace) -> int:
    from .espaco import ARQUIVOS_DE_SISTEMA, calcular

    unidades = sorted({Path(a).anchor for a in AREAS_DE_LEITURA})
    with Indice(args.indice) as indice:
        for unidade in unidades:
            e = calcular(indice, unidade)
            pct = lambda v: f"{v / e.usado * 100:4.1f}%" if e.usado else "  -  "  # noqa: E731
            _titulo(f"Unidade {e.unidade}  ({formatar_bytes(e.total)}; {formatar_bytes(e.livre)} livres)")
            print(f"  Usado no disco:                         {formatar_bytes(e.usado):>10}")
            print(f"  Explicado pelo índice (seus arquivos):  {formatar_bytes(e.explicado):>10}  {pct(e.explicado)}")
            if e.programas:
                print(f"    dentro disso, pastas de programa ({formatar_bytes(sum(e.programas.values()))};"
                      " o Raio-X não lista o que tem dentro):")
                for caminho, tamanho in list(e.programas.items())[:LIMITE_PROGRAMAS]:
                    print(f"      {formatar_bytes(tamanho):>10}  {caminho}")
                if len(e.programas) > LIMITE_PROGRAMAS:
                    resto = list(e.programas.values())[LIMITE_PROGRAMAS:]
                    print(f"      {formatar_bytes(sum(resto)):>10}  ... e mais {len(resto)} pastas menores")
            for nome, tamanho in e.sistema.items():
                print(f"  {ARQUIVOS_DE_SISTEMA[nome][:38]:<38} {formatar_bytes(tamanho):>10}  {pct(tamanho)}")
            for rotulo, tamanho in e.backups.items():
                print(f"  {rotulo}:")
                print(f"  {'':<38} {formatar_bytes(tamanho):>10}  {pct(tamanho)}")
            print(f"  Não explicado:                          {formatar_bytes(e.nao_explicado):>10}  {pct(e.nao_explicado)}")
            print("    (Windows, programas, AppData, lixeira, pontos de restauração e pastas bloqueadas —")
            print("     só o total; o app não entra nessas pastas)")
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


def _raiox_de(indice: Indice, base: Path, args: argparse.Namespace, ctrl_c) -> int:
    if not indice.foi_escaneada(str(base)):
        print(f"{base} ainda não foi escaneada. Rode antes: python -m faxineiro escanear", file=sys.stderr)
        return 1
    _titulo(f"RAIO-X de {base}")
    hasher = Hasher()

    def progresso(p: raiox.ProgressoHash) -> None:
        print(f"\rCalculando hashes: {_numero(p.feitos)}/{_numero(p.total)} arquivos, "
              f"{formatar_bytes(p.bytes_lidos)} lidos", end="", flush=True, file=sys.__stdout__)

    dup = raiox.encontrar_duplicados(indice, base, hasher=hasher, ao_progredir=progresso,
                                     parar=lambda: ctrl_c.pedido)
    print("", file=sys.__stdout__)
    print(f"Hashes calculados agora: {_numero(hasher.parciais)} parciais, {_numero(hasher.completos)} completos, "
          f"{formatar_bytes(hasher.bytes_lidos)} lidos (o resto veio do índice)")
    if dup.cancelado:
        print("Duplicados: CANCELADO — os hashes feitos ficaram guardados; rode de novo para terminar.")
    lx = raiox.lixo(indice, base)
    errados = raiox.extensao_errada(indice, base)
    vazias = raiox.pastas_vazias(base, _bloqueios_para(base))
    minimo = minimo_pesado(args)
    grandes = raiox.pesados(indice, base, args.top, minimo)

    _titulo("Resumo")
    print(f"Dá para liberar {formatar_bytes(dup.recuperavel + lx.recuperavel)} sem perder nada "
          f"(cópias repetidas {formatar_bytes(dup.recuperavel)} + temporários {formatar_bytes(lx.recuperavel)})")
    print(f"{_numero(len(dup.grupos))} grupos de duplicados | {_numero(len(lx.temporarios))} temporários | "
          f"{_numero(len(lx.vazios))} arquivos vazios | {_numero(len(vazias))} pastas vazias | "
          f"{_numero(len(errados))} com extensão errada")

    _titulo(f"Os {args.top} maiores (a partir de {formatar_bytes(minimo)})")
    if not grandes:
        print(f"  Nenhum arquivo com {formatar_bytes(minimo)} ou mais.")
    for a in grandes:
        print(f"  {formatar_bytes(a['tamanho']):>10}  {_relativo(a['caminho'], base)}")

    _titulo(f"Maiores grupos de duplicados (os {min(LIMITE_GRUPOS, len(dup.grupos))} que mais liberam)")
    if not dup.grupos:
        print("Nenhum duplicado encontrado.")
    for i, g in enumerate(dup.grupos[:LIMITE_GRUPOS], 1):
        print(f"Grupo {i}: {len(g.arquivos)} cópias de {formatar_bytes(g.tamanho)} — liberaria {formatar_bytes(g.recuperavel)}")
        for a in g.arquivos[:6]:
            marca = "fica →" if a["id"] == g.manter["id"] else "      "
            print(f"  {marca} {_relativo(a['caminho'], base)}")
        if len(g.arquivos) > 6:
            print(f"         ... e mais {len(g.arquivos) - 6} cópia(s)")
    if len(dup.grupos) > LIMITE_GRUPOS:
        print(f"... e mais {_numero(len(dup.grupos) - LIMITE_GRUPOS)} grupos menores.")
    if dup.desatualizados:
        print(f"  aviso: {_numero(len(dup.desatualizados))} arquivo(s) mudaram desde a varredura (ficaram de fora)")

    _titulo("Lixo")
    temporarios = sorted(lx.temporarios, key=lambda a: a["tamanho"], reverse=True)
    for a in temporarios[:LIMITE_LISTA]:
        print(f"  temporário: {_relativo(a['caminho'], base)} ({formatar_bytes(a['tamanho'])})")
    if len(temporarios) > LIMITE_LISTA:
        print(f"  ... e mais {_numero(len(temporarios) - LIMITE_LISTA)} temporários")
    print(f"  arquivos vazios: {_numero(len(lx.vazios))}" + (f" (ex.: {_relativo(lx.vazios[0]['caminho'], base)})" if lx.vazios else ""))
    for p in vazias[:10]:
        print(f"  pasta vazia: {_relativo(p, base)}")
    if len(vazias) > 10:
        print(f"  ... e mais {_numero(len(vazias) - 10)} pastas vazias")

    _titulo("Extensão errada (suspeito, não é lixo)")
    for a in errados[:10]:
        print(f"  {_relativo(a['caminho'], base)}: o conteúdo é {a['tipo_real']}")
    if len(errados) > 10:
        print(f"  ... e mais {_numero(len(errados) - 10)}")
    if not errados:
        print("Nada encontrado.")
    return 0


class _Duplo:
    """Escreve na tela e num arquivo ao mesmo tempo (relatório do PC real fica em dados/, fora do Git)."""

    def __init__(self, *saidas) -> None:
        self.saidas = saidas

    def write(self, texto: str) -> int:
        for s in self.saidas:
            s.write(texto)
        return len(texto)

    def flush(self) -> None:
        for s in self.saidas:
            s.flush()


def cmd_raiox(args: argparse.Namespace) -> int:
    from .cli_ia import _CtrlC
    from .descricoes import baixar_prioridade

    bases = list(AREAS_DE_LEITURA) if args.pc else [Path(args.pasta)]
    for b in bases:
        if (erro := _pasta_legivel(b)) is not None:
            return erro
    baixar_prioridade()
    relatorio = None
    if args.pc:
        pasta_rel = RAIZ_PROJETO / "dados" / "relatorios"
        pasta_rel.mkdir(parents=True, exist_ok=True)
        relatorio = pasta_rel / f"raiox_{datetime.now():%Y-%m-%d_%H%M}.txt"
    codigo = 0
    with Indice(args.indice) as indice, _CtrlC() as ctrl_c, contextlib.ExitStack() as pilha:
        if relatorio:
            arq = pilha.enter_context(open(relatorio, "w", encoding="utf-8"))
            pilha.enter_context(contextlib.redirect_stdout(_Duplo(sys.stdout, arq)))
        for base in bases:
            codigo = max(codigo, _raiox_de(indice, base.resolve(), args, ctrl_c))
            if ctrl_c.pedido:
                break
        print()
        print("O Raio-X só mostra. Nada foi movido nem apagado.")
    if relatorio:
        print(f"Relatório salvo em {relatorio} (fora do Git).")
    return codigo


def cmd_gui(args: argparse.Namespace) -> int:
    try:
        from .gui.app import principal
    except ImportError:
        print("A interface precisa do PySide6: .venv\\Scripts\\python -m pip install PySide6-Essentials",
              file=sys.stderr)
        return 1
    return principal()


def _saida_em_utf8() -> None:
    """No Windows, saída redirecionada (arquivo/pipe) usa cp1252 e quebra com "→" e "…"."""
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _saida_em_utf8()
    parser = argparse.ArgumentParser(prog="faxineiro")
    sub = parser.add_subparsers(dest="comando", required=True)

    esc = sub.add_parser("escanear", help="varre uma pasta e atualiza o índice (só lê)")
    esc.add_argument("pasta", nargs="?", default=str(PASTA_TESTE))
    esc.add_argument("--pc", action="store_true",
                     help="varre o PC real (áreas de leitura do config.py), só leitura; Ctrl+C cancela")
    esc.add_argument("--indice", default=str(CAMINHO_INDICE), help=argparse.SUPPRESS)
    esc.set_defaults(func=cmd_escanear)

    rx = sub.add_parser("raiox", help="mostra duplicados, arquivos pesados e lixo (só lê)")
    rx.add_argument("pasta", nargs="?", default=str(PASTA_TESTE))
    rx.add_argument("--pc", action="store_true", help="Raio-X do PC real, separado por área; salva o relatório em dados/")
    rx.add_argument("--top", type=int, default=TOP_PESADOS, help="quantos arquivos pesados mostrar")
    rx.add_argument("--minimo-mb", type=float, default=None,
                    help=f"tamanho mínimo de um arquivo pesado, em MB (padrão {PESADO_MINIMO // MB})")
    rx.add_argument("--teste", action="store_true",
                    help=f"modo de teste: mínimo de {PESADO_MINIMO_TESTE // MB} MB para a pasta_teste")
    rx.add_argument("--indice", default=str(CAMINHO_INDICE), help=argparse.SUPPRESS)
    rx.set_defaults(func=cmd_raiox)

    es = sub.add_parser("espaco", help="quanto do disco o índice explica e quanto fica 'não explicado'")
    es.add_argument("--indice", default=str(CAMINHO_INDICE), help=argparse.SUPPRESS)
    es.set_defaults(func=cmd_espaco)

    cli_quarentena.registrar(sub)
    cli_ia.registrar(sub)
    cli_conversor.registrar(sub)
    cli_sistema.registrar(sub)

    g = sub.add_parser("gui", help="abre a janela do Faxineiro")
    g.set_defaults(func=cmd_gui)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
