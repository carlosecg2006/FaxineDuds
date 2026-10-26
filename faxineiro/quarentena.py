"""Quarentena com diário de operações, recuperação após travamento e desfazer.

Toda operação tem duas etapas:
  1. planejar_*()  → devolve um Plano (a prévia / dry-run). Nada no disco muda.
  2. executar(plano) → executa, gravando cada passo no diário ANTES de mexer no disco.

"Excluir" nunca apaga: move (renomeia) para a `_quarentena` da mesma unidade.
A única operação que apaga de vez é esvaziar a quarentena (exceção da regra 1).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import raiox
from .config import PASTA_TESTE, dentro_da_pasta_teste, pasta_quarentena
from .hashes import Hasher
from .indice import Indice
from .scanner import indexar_arquivo

# Ganchos usados pelos testes para simular travamento em pontos críticos.
ANTES_DE_MEXER = "antes_de_mexer"  # diário já gravado, disco ainda intacto
DEPOIS_DE_MEXER = "depois_de_mexer"  # disco já mudou, diário ainda diz "em andamento"


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Passo:
    origem: Path
    destino: Path | None  # quarentena: definido na execução (depende do número do lote)
    tamanho: int
    hash_esperado: str | None = None
    pasta_raiz: str | None = None
    ref_operacao: int | None = None  # restaurar/esvaziar: a operação de quarentena original
    manter: Path | None = None  # duplicados: a cópia que fica (precisa existir e ser igual)
    problema: str | None = None  # se preenchido, o passo não será executado
    renomeado: bool = False  # restaurar com outro nome por causa de conflito


@dataclass
class Plano:
    tipo: str  # quarentena | restaurar | esvaziar
    descricao: str
    passos: list[Passo] = field(default_factory=list)

    @property
    def validos(self) -> list[Passo]:
        return [p for p in self.passos if p.problema is None]

    @property
    def total_bytes(self) -> int:
        return sum(p.tamanho for p in self.validos)


@dataclass
class Resultado:
    lote_id: int | None = None
    feitos: list[Passo] = field(default_factory=list)
    falhas: list[tuple[Passo, str]] = field(default_factory=list)


class OperacaoRecusada(Exception):
    pass


class Quarentena:
    def __init__(
        self,
        indice: Indice,
        *,
        limite: Path = PASTA_TESTE,
        local: Callable[[Path], Path] | None = None,
        hasher: Hasher | None = None,
        gancho: Callable[[str, Passo], None] | None = None,
    ) -> None:
        """`limite`: nada fora desta pasta é tocado (trava da regra 5).
        `local`: diz onde fica a quarentena de cada arquivo (padrão: config.pasta_quarentena)."""
        self.indice = indice
        self.limite = Path(limite).resolve()
        self.local = local or (lambda arq: pasta_quarentena(arq))
        self.hasher = hasher or Hasher()
        self.gancho = gancho or (lambda momento, passo: None)

    # --- travas -------------------------------------------------------------

    def _conferir_limite(self, *caminhos: Path) -> None:
        for c in caminhos:
            if not dentro_da_pasta_teste(c, self.limite):
                raise OperacaoRecusada(f"Fora da área permitida ({self.limite}): {c}")

    @staticmethod
    def _mesma_unidade(a: Path, b: Path) -> bool:
        return Path(a).resolve().drive.casefold() == Path(b).resolve().drive.casefold()

    def _destino_na_quarentena(self, origem: Path, lote_id: int) -> Path:
        """_quarentena\\0003\\<caminho relativo>\\arquivo.ext — mantém as pastas e evita colisões.

        O caminho é relativo à pasta onde a quarentena mora (raiz da unidade em produção,
        pasta_teste em desenvolvimento), para não estourar o limite de 260 caracteres do Windows.
        """
        origem = origem.resolve()
        raiz_q = self.local(origem)
        try:
            relativo = origem.relative_to(raiz_q.parent)
        except ValueError:
            relativo = Path(*origem.parts[1:])
        return raiz_q / f"{lote_id:04d}" / relativo

    # --- recuperação após travamento -----------------------------------------

    def recuperar_diario(self) -> list[str]:
        """Termina ou marca como falha as operações que ficaram pela metade."""
        mensagens = []
        for op in self.indice.operacoes_em_andamento():
            origem, destino = Path(op["origem"]), Path(op["destino"])
            tem_origem, tem_destino = origem.exists(), destino.exists()
            agora = _agora()

            if op["tipo"] == "esvaziar":
                if not tem_origem:
                    self._concluir_esvaziar(op["id"], op["ref_operacao"], agora)
                    mensagens.append(f"Concluída (esvaziar): {origem}")
                else:
                    self.indice.concluir_operacao(op["id"], "falhou", agora, "interrompida; nada foi apagado")
                    mensagens.append(f"Interrompida, nada foi apagado: {origem}")
            elif tem_destino and not tem_origem:
                try:
                    if op["tipo"] == "quarentena":
                        self._concluir_quarentena(op["id"], origem, agora)
                    else:
                        self._concluir_restaurar(op, destino, agora)
                    mensagens.append(f"Concluída ({op['tipo']}): {origem} → {destino}")
                except OperacaoRecusada as erro:
                    mensagens.append(f"Concluída com aviso ({op['tipo']}): {destino}: {erro}")
            elif tem_origem and not tem_destino:
                self.indice.concluir_operacao(op["id"], "falhou", agora, "interrompida; nada mudou")
                mensagens.append(f"Interrompida, nada mudou: {origem}")
            else:
                situacao = "os dois existem" if tem_origem else "nenhum dos dois existe"
                self.indice.concluir_operacao(op["id"], "falhou", agora, f"verificar à mão: {situacao}")
                mensagens.append(f"ATENÇÃO, verificar à mão ({situacao}): {origem} / {destino}")
        self.indice.confirmar()
        return mensagens

    # --- planejar (prévia) ----------------------------------------------------

    def planejar_mover(self, caminhos: Iterable[str | Path], descricao: str = "excluir") -> Plano:
        plano = Plano("quarentena", descricao)
        vistos: set[Path] = set()
        for c in caminhos:
            origem = Path(c).resolve()
            if origem in vistos:
                continue
            vistos.add(origem)
            passo = Passo(origem=origem, destino=None, tamanho=0)
            linha = self.indice.buscar(str(origem))
            if linha is not None:
                passo.pasta_raiz = linha["pasta_raiz"]
                passo.hash_esperado = linha["hash_completo"]
            if not origem.is_file():
                passo.problema = "arquivo não encontrado"
            elif not dentro_da_pasta_teste(origem, self.limite):
                passo.problema = f"fora da área permitida ({self.limite})"
            elif not self._mesma_unidade(origem, self.local(origem)):
                passo.problema = "a quarentena fica em outra unidade (não copio arquivos)"
            else:
                passo.tamanho = origem.stat().st_size
            plano.passos.append(passo)
        return plano

    def planejar_duplicados(self, pasta: str | Path) -> Plano:
        """Para cada grupo do Raio-X, manda para a quarentena todos menos o sugerido."""
        r = raiox.encontrar_duplicados(self.indice, pasta, hasher=self.hasher)
        plano = Plano("quarentena", "duplicados do Raio-X")
        for grupo in r.grupos:
            manter = Path(grupo.manter["caminho"])
            outros = [a["caminho"] for a in grupo.arquivos if a["id"] != grupo.manter["id"]]
            for passo in self.planejar_mover(outros).passos:
                passo.hash_esperado = grupo.hash_completo
                passo.manter = manter
                plano.passos.append(passo)
        return plano

    def planejar_desfazer(
        self,
        *,
        item: int | None = None,
        lote: int | None = None,
        conflito: str | Callable[[Path], str] = "renomear",
    ) -> Plano:
        """Traz de volta da quarentena. Nunca sobrescreve: em conflito, renomeia ou pula.

        `conflito`: "renomear", "pular" ou uma função que recebe o caminho original e
        devolve "renomear" ou "pular" (a CLI usa isso para perguntar ao usuário).
        """
        if item is None and lote is None:
            raise ValueError("Informe item ou lote.")
        plano = Plano("restaurar", f"desfazer {'item ' + str(item) if item else 'lote ' + str(lote)}")
        reservados: set[Path] = set()
        for op in self.indice.itens_na_quarentena(item=item, lote=lote):
            na_quarentena, original = Path(op["destino"]), Path(op["origem"])
            passo = Passo(
                origem=na_quarentena, destino=original, tamanho=op["tamanho"] or 0,
                hash_esperado=op["hash_completo"], pasta_raiz=op["pasta_raiz"], ref_operacao=op["id"],
            )
            if not na_quarentena.is_file():
                passo.problema = "não está mais na quarentena"
            elif original.exists() or original in reservados:
                escolha = conflito(original) if callable(conflito) else conflito
                if escolha == "renomear":
                    passo.destino = self._nome_livre(original, reservados)
                    passo.renomeado = True
                else:
                    passo.problema = "já existe um arquivo com esse nome no lugar original (pulado)"
            if passo.problema is None:
                reservados.add(passo.destino)
            plano.passos.append(passo)
        return plano

    @staticmethod
    def _nome_livre(original: Path, reservados: set[Path]) -> Path:
        n = 1
        while True:
            sufixo = " (restaurado)" if n == 1 else f" (restaurado {n})"
            candidato = original.with_name(f"{original.stem}{sufixo}{original.suffix}")
            if not candidato.exists() and candidato not in reservados:
                return candidato
            n += 1

    def planejar_esvaziar(self) -> Plano:
        """Lista o que seria APAGADO DE VEZ: só itens do histórico que ainda estão na quarentena."""
        plano = Plano("esvaziar", "esvaziar a quarentena (apaga de vez)")
        for op in self.indice.itens_na_quarentena():
            caminho = Path(op["destino"])
            passo = Passo(origem=caminho, destino=None, tamanho=op["tamanho"] or 0,
                          hash_esperado=op["hash_completo"], ref_operacao=op["id"])
            if not caminho.is_file():
                passo.problema = "não está mais na quarentena"
            plano.passos.append(passo)
        return plano

    # --- executar --------------------------------------------------------------

    def executar(self, plano: Plano) -> Resultado:
        resultado = Resultado()
        if not plano.validos:
            return resultado
        resultado.lote_id = self.indice.criar_lote(plano.tipo, plano.descricao, _agora())
        self.indice.confirmar()
        acao = {"quarentena": self._mover, "restaurar": self._restaurar, "esvaziar": self._apagar}[plano.tipo]
        hashes_mantidos: dict[Path, str] = {}
        for passo in plano.validos:
            try:
                acao(passo, resultado.lote_id, hashes_mantidos)
                resultado.feitos.append(passo)
            except (OSError, OperacaoRecusada) as erro:
                mensagem = erro.strerror if isinstance(erro, OSError) and erro.strerror else str(erro)
                resultado.falhas.append((passo, mensagem))
        if plano.tipo in ("esvaziar", "restaurar"):
            self._remover_pastas_vazias()
        self.indice.confirmar()
        return resultado

    def _mover(self, passo: Passo, lote_id: int, hashes_mantidos: dict[Path, str]) -> None:
        origem = passo.origem
        destino = self._destino_na_quarentena(origem, lote_id)
        self._conferir_limite(origem, destino)
        if not self._mesma_unidade(origem, destino):
            raise OperacaoRecusada("a quarentena fica em outra unidade (não copio arquivos)")

        hash_atual = self.hasher.completo(origem)
        if passo.hash_esperado and hash_atual != passo.hash_esperado:
            raise OperacaoRecusada("o arquivo mudou desde a prévia; rode escanear e tente de novo")
        if passo.manter is not None:
            # Nunca manda a última cópia: a que fica tem que existir e ser igual.
            if passo.manter not in hashes_mantidos:
                if not passo.manter.is_file():
                    raise OperacaoRecusada(f"a cópia que ficaria sumiu: {passo.manter}")
                hashes_mantidos[passo.manter] = self.hasher.completo(passo.manter)
            if hashes_mantidos[passo.manter] != hash_atual:
                raise OperacaoRecusada(f"a cópia que ficaria não é mais igual: {passo.manter}")
        if destino.exists():
            raise OperacaoRecusada(f"já existe algo no destino: {destino}")

        destino.parent.mkdir(parents=True, exist_ok=True)
        passo.destino = destino
        op_id = self.indice.registrar_operacao(
            lote_id=lote_id, tipo="quarentena", origem=str(origem), destino=str(destino),
            pasta_raiz=passo.pasta_raiz, tamanho=passo.tamanho, hash_completo=hash_atual,
            ref_operacao=None, agora=_agora(),
        )
        self.gancho(ANTES_DE_MEXER, passo)
        os.rename(origem, destino)  # mesma unidade: instantâneo, não copia
        self.gancho(DEPOIS_DE_MEXER, passo)
        self._concluir_quarentena(op_id, origem, _agora())
        self.indice.confirmar()

    def _concluir_quarentena(self, op_id: int, origem: Path, agora: str) -> None:
        self.indice.concluir_operacao(op_id, "feita", agora, situacao="na_quarentena")
        self.indice.remover_arquivo(str(origem))

    def _restaurar(self, passo: Passo, lote_id: int, _: dict[Path, str]) -> None:
        origem, destino = passo.origem, passo.destino
        assert destino is not None
        self._conferir_limite(origem, destino)
        if passo.hash_esperado and self.hasher.completo(origem) != passo.hash_esperado:
            raise OperacaoRecusada("o arquivo na quarentena não bate com o hash do histórico; não mexi")
        if destino.exists():
            raise OperacaoRecusada(f"já existe um arquivo em {destino}; não sobrescrevo")

        destino.parent.mkdir(parents=True, exist_ok=True)
        op_id = self.indice.registrar_operacao(
            lote_id=lote_id, tipo="restaurar", origem=str(origem), destino=str(destino),
            pasta_raiz=passo.pasta_raiz, tamanho=passo.tamanho, hash_completo=passo.hash_esperado,
            ref_operacao=passo.ref_operacao, agora=_agora(),
        )
        self.gancho(ANTES_DE_MEXER, passo)
        os.rename(origem, destino)
        self.gancho(DEPOIS_DE_MEXER, passo)
        self._concluir_restaurar(self.indice.operacao(op_id), destino, _agora())
        self.indice.confirmar()

    def _concluir_restaurar(self, op, destino: Path, agora: str) -> None:
        erro = None
        if op["hash_completo"] and self.hasher.completo(destino) != op["hash_completo"]:
            erro = "voltou com hash diferente do original"
        self.indice.concluir_operacao(op["id"], "feita", agora, erro)
        self.indice.mudar_situacao(op["ref_operacao"], "restaurado")
        pasta_raiz = op["pasta_raiz"] or str(destino.parent)
        indexar_arquivo(destino, self.indice, pasta_raiz)
        if erro:
            raise OperacaoRecusada(erro)

    def _apagar(self, passo: Passo, lote_id: int, _: dict[Path, str]) -> None:
        caminho = passo.origem
        self._conferir_limite(caminho)
        if passo.hash_esperado and self.hasher.completo(caminho) != passo.hash_esperado:
            raise OperacaoRecusada("o arquivo na quarentena não bate com o histórico; não apaguei")
        op_id = self.indice.registrar_operacao(
            lote_id=lote_id, tipo="esvaziar", origem=str(caminho), destino="",
            pasta_raiz=None, tamanho=passo.tamanho, hash_completo=passo.hash_esperado,
            ref_operacao=passo.ref_operacao, agora=_agora(),
        )
        self.gancho(ANTES_DE_MEXER, passo)
        os.remove(caminho)  # única remoção definitiva do app (regra 1, exceção do Esvaziar)
        self.gancho(DEPOIS_DE_MEXER, passo)
        self._concluir_esvaziar(op_id, passo.ref_operacao, _agora())
        self.indice.confirmar()

    def _concluir_esvaziar(self, op_id: int, ref_operacao: int | None, agora: str) -> None:
        self.indice.concluir_operacao(op_id, "feita", agora)
        if ref_operacao is not None:
            self.indice.mudar_situacao(ref_operacao, "esvaziado")

    def _remover_pastas_vazias(self) -> None:
        """Depois de esvaziar/desfazer, remove só as pastas que ficaram vazias dentro da quarentena."""
        raizes = {self.local(self.limite)}
        for raiz in raizes:
            if not raiz.is_dir():
                continue
            for pasta, subpastas, arquivos in os.walk(raiz, topdown=False):
                if Path(pasta) != raiz and not os.listdir(pasta):
                    os.rmdir(pasta)  # rmdir só remove pasta vazia
