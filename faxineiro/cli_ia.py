"""Comandos da IA: status, descrever e organizar."""

from __future__ import annotations

import argparse
import signal
import sys
import time
from collections import Counter
from pathlib import Path

from . import cli_quarentena
from .config import CAMINHO_INDICE, MODELO_IA, PASTA_TESTE, dentro_da_pasta_teste
from .descricoes import (
    ARQUIVOS_PARA_MEDIR,
    ConfigDescricao,
    ProgressoDescricao,
    baixar_prioridade,
    descrever,
    descrever_arquivo,
)
from .formato import formatar_duracao, relativo
from .ia import ClienteOllama, EnderecoNaoLocal, avaliar_ia, memoria_necessaria
from .indice import Indice
from .memoria import MB, memoria_disponivel, memoria_total
from .organizacao import planejar_organizacao, sugerir_pastas
from .quarentena import Quarentena


def _cliente(modelo: str | None = None) -> ClienteOllama | None:
    try:
        return ClienteOllama(modelo=modelo)
    except EnderecoNaoLocal as erro:
        print(f"Recusado: {erro}", file=sys.stderr)
        return None


def _pasta_ok(pasta: Path) -> bool:
    if not dentro_da_pasta_teste(pasta):
        print(f"Recusado: durante o desenvolvimento só posso trabalhar em {PASTA_TESTE}.", file=sys.stderr)
        return False
    return True


class _CtrlC:
    """1º Ctrl+C = pausar com calma (termina o arquivo atual e grava). 2º = sair na hora."""

    def __init__(self) -> None:
        self.pedido = False

    def __enter__(self) -> _CtrlC:
        self._antigo = signal.signal(signal.SIGINT, self._tratar)
        return self

    def _tratar(self, *_: object) -> None:
        if self.pedido:
            raise KeyboardInterrupt
        self.pedido = True
        print("\nPausando... (termina o arquivo atual e grava)", flush=True)

    def __exit__(self, *_: object) -> None:
        signal.signal(signal.SIGINT, self._antigo)


def cmd_status(args: argparse.Namespace) -> int:
    cliente = _cliente(args.modelo)
    if cliente is None:
        return 2
    livre, total = memoria_disponivel(), memoria_total()
    if livre is not None:
        print(f"Memória: {livre // MB} MB disponíveis de {(total or 0) // MB} MB")
    st, pode, aviso = avaliar_ia(cliente)
    if not st.ligado:
        print(f"Ollama: DESLIGADO ({st.erro})")
        print("O Faxineiro vai usar só regras (tipo e data) e marcar para revisar o que precisa de IA.")
        return 1
    print(f"Ollama: ligado (versão {st.versao}) em {cliente.base} — só neste PC")
    for nome in st.modelos:
        marca = " ← em uso" if nome == cliente.modelo else ""
        precisa = memoria_necessaria(st, nome) // MB
        print(f"  {nome:<16} arquivo {st.tamanhos.get(nome, 0) // MB:>5} MB | precisa de ~{precisa} MB livres{marca}")
    print(f"Modelo configurado: {cliente.modelo} (troque com --modelo ou FAXINEIRO_MODELO)")
    print(f"Visão (imagens): {st.modelo_visao or 'não instalado — imagens são descritas por regras'}")
    print(f"Agora: {'dá para usar a IA' if pode else aviso}")
    return 0


def cmd_descrever(args: argparse.Namespace) -> int:
    pasta = Path(args.pasta)
    if not _pasta_ok(pasta):
        return 2
    cliente = _cliente(args.modelo)
    baixar_prioridade()
    inicio = time.monotonic()

    def progresso(p: ProgressoDescricao) -> None:
        if p.fase == "inicio":
            print(f"Regras resolveram {p.por_regras} arquivo(s) novo(s) sem IA (óbvios pelo nome, tipo ou pasta).")
            print(f"Faltam {p.total} arquivo(s) para a IA — ordem: Downloads, Área de Trabalho, Documentos, resto.")
            print(f"Estimativa: medindo os primeiros {ARQUIVOS_PARA_MEDIR} arquivos...", flush=True)
        elif p.fase == "estimativa":
            media = sum(p.tempos) / len(p.tempos)
            print(f"\nEstimativa: ~{formatar_duracao(p.estimativa_s)} para os {p.faltam} restantes "
                  f"({media:.1f} s por arquivo).", flush=True)
        elif p.total:
            print(f"\rIA: {p.feitos}/{p.total} ({p.por_ia} descritos) | faltam ~{formatar_duracao(p.estimativa_s)}   ",
                  end="", flush=True)

    with Indice(args.indice) as indice, _CtrlC() as ctrl_c:
        if not indice.foi_escaneada(str(pasta.resolve())):
            print("Esta pasta ainda não foi escaneada. Rode antes: python -m faxineiro escanear", file=sys.stderr)
            return 1
        p = descrever(indice, pasta, cliente, limite=args.limite, so_regras=args.so_regras,
                      parar=lambda: ctrl_c.pedido, ao_progredir=progresso,
                      cfg=ConfigDescricao(timeout=args.timeout))
    print()
    if p.por_regras == 0 and p.total == 0:
        print("Nada novo: tudo já tem descrição e nada está marcado para revisar (só refaço o que mudar).")
    for aviso in dict.fromkeys(p.avisos):  # sem repetir
        print(f"  aviso: {aviso}")
    print(f"Tempo: {time.monotonic() - inicio:.1f} s. Nenhum conteúdo saiu do PC.")
    if p.pausado:
        print(f"Pausado em {p.feitos}/{p.total}. Rode o mesmo comando para continuar de onde parou.")
    return 0


def cmd_arquivo(args: argparse.Namespace) -> int:
    """Descreve UM arquivo com a IA, quando o usuário pede."""
    alvo = Path(args.arquivo)
    if not _pasta_ok(alvo):
        return 2
    cliente = _cliente(args.modelo)
    inicio = time.monotonic()
    with Indice(args.indice) as indice:
        p = descrever_arquivo(indice, alvo, cliente, cfg=ConfigDescricao(timeout=args.timeout))
        linha = indice.buscar(str(alvo.resolve()))
    for aviso in dict.fromkeys(p.avisos):
        print(f"  aviso: {aviso}")
    if linha is not None and linha["descricao"]:
        quem = {"ia": f"IA ({cliente.modelo if cliente else '?'})", "ia_visao": "IA com visão",
                "regras": "regras"}[linha["descricao_origem"]]
        print(f"{linha['nome']}: {linha['descricao']}")
        print(f"  (por {quem}, em {time.monotonic() - inicio:.1f} s{'; marcado para revisar' if linha['revisar'] else ''})")
    return 0 if linha is not None else 1


def cmd_organizar(args: argparse.Namespace) -> int:
    pasta = Path(args.pasta)
    if not _pasta_ok(pasta):
        return 2
    base = pasta.resolve()
    cliente = _cliente(args.modelo)
    baixar_prioridade()
    with Indice(args.indice) as indice, _CtrlC() as ctrl_c:
        q = Quarentena(indice, limite=PASTA_TESTE)
        for msg in q.recuperar_diario():
            print(f"[diário] {msg}")
        print("Pensando nas pastas...", flush=True)
        r = sugerir_pastas(indice, base, cliente, refazer=args.refazer, parar=lambda: ctrl_c.pedido)
        for aviso in dict.fromkeys(r.avisos):
            print(f"  aviso: {aviso}")
        if r.sem_descricao:
            print(f"  aviso: {r.sem_descricao} arquivo(s) sem descrição; rode antes `ia descrever` para sugestões melhores.")
        if r.pausado:
            print("Pausado. Rode de novo para continuar as sugestões.")
            return 0

        plano = planejar_organizacao(indice, base, q)
        if plano.ignorados:
            print("== Protegidos (o organizar não mexe) ".ljust(60, "="))
            por_motivo: dict[str, list[Path]] = {}
            for arquivo, motivo in plano.ignorados:
                por_motivo.setdefault(motivo, []).append(arquivo)
            for motivo, arquivos in sorted(por_motivo.items()):
                print(f"  {len(arquivos)} arquivo(s): {motivo}")
            print()
        destinos = Counter(relativo(p.destino.parent, base) for p in plano.validos)
        print("== Estrutura proposta ".ljust(60, "="))
        for pasta_nova, n in sorted(destinos.items()):
            print(f"  {pasta_nova}\\  ({n} arquivo(s))")
        print()
        for i, p in enumerate(plano.passos, 1):
            if p.problema:
                print(f"  {i:>3}. PULA {relativo(p.origem, base)} — {p.problema}")
            else:
                nota = "  (nome trocado: já existe um igual lá)" if p.renomeado else ""
                print(f"  {i:>3}. {relativo(p.origem, base)}  →  {relativo(p.destino, base)}{nota}")
        origem = (f"sugestões novas: {r.por_ia} pela IA, {r.por_regras} por regras" if r.sugeridos
                  else "sugestões guardadas da última vez; use --refazer para pedir novas")
        print(f"Total: {len(plano.validos)} arquivo(s) a mover. ({origem})")
        if not plano.validos:
            print("Nada a mover: tudo já está nas pastas sugeridas.")
            return 0
        if args.so_previa:
            print("(só prévia: nada foi movido)")
            return 0
        if not cli_quarentena._confirmar("Aplicar esta organização?", args):
            print("Cancelado. Nada foi movido.")
            return 0
        res = q.executar(plano)
    print(f"Lote {res.lote_id}: {len(res.feitos)} movidos, {len(res.falhas)} com problema.")
    for passo, msg in res.falhas:
        print(f"  problema: {relativo(passo.origem, base)}: {msg}")
    print(f"Para desfazer tudo: python -m faxineiro quarentena desfazer --lote {res.lote_id}")
    return 0 if not res.falhas else 1


def registrar(sub: argparse._SubParsersAction) -> None:
    ia = sub.add_parser("ia", help="IA local (Ollama): descrever arquivos e sugerir pastas")
    isub = ia.add_subparsers(dest="acao", required=True)

    def modelo(p: argparse.ArgumentParser) -> None:
        p.add_argument("--modelo", default=None,
                       help=f"modelo do Ollama (padrão {MODELO_IA}; ex.: qwen2.5:3b com mais RAM)")

    s = isub.add_parser("status", help="o Ollama está ligado? quais modelos? tem memória?")
    modelo(s)
    s.set_defaults(func=cmd_status)

    d = isub.add_parser("descrever", help="regras descrevem tudo; a IA só o que ficou para revisar")
    d.add_argument("pasta", nargs="?", default=str(PASTA_TESTE))
    d.add_argument("--limite", type=int, default=None, help="IA em no máximo N arquivos nesta rodada")
    d.add_argument("--so-regras", action="store_true", help="não usa a IA (só as regras)")
    d.add_argument("--timeout", type=float, default=60, help="tempo limite por arquivo, em segundos")
    d.add_argument("--indice", default=str(CAMINHO_INDICE), help=argparse.SUPPRESS)
    modelo(d)
    d.set_defaults(func=cmd_descrever)

    a = isub.add_parser("arquivo", help="descreve UM arquivo com a IA, agora")
    a.add_argument("arquivo")
    a.add_argument("--timeout", type=float, default=120)
    a.add_argument("--indice", default=str(CAMINHO_INDICE), help=argparse.SUPPRESS)
    modelo(a)
    a.set_defaults(func=cmd_arquivo)

    o = isub.add_parser("organizar", help="a IA sugere pastas; aplica com prévia e desfazer")
    modelo(o)
    o.add_argument("pasta", nargs="?", default=str(PASTA_TESTE))
    o.add_argument("--refazer", action="store_true", help="pede novas sugestões para todos")
    o.add_argument("--so-previa", action="store_true")
    o.add_argument("--sim", action="store_true", help="não pergunta (a prévia aparece mesmo assim)")
    o.add_argument("--indice", default=str(CAMINHO_INDICE), help=argparse.SUPPRESS)
    o.set_defaults(func=cmd_organizar)
