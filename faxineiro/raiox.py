"""Raio-X: duplicados, arquivos pesados e lixo. Só lê; nunca move nem apaga nada."""

from __future__ import annotations

import os
import sqlite3
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import config
from .config import Bloqueios
from .hashes import TAMANHO_PARCIAL, Hasher
from .indice import Indice
from .tipos import extensao_confere


def prefixo_da_pasta(pasta: str | Path) -> str:
    """Caminho absoluto com separador no fim, para filtrar a pasta e suas subpastas."""
    return str(Path(pasta).resolve()).rstrip("\\/") + os.sep


# --- duplicados -----------------------------------------------------------


@dataclass
class ProgressoHash:
    total: int = 0
    feitos: int = 0
    bytes_lidos: int = 0
    terminou: bool = False


@dataclass
class GrupoDuplicado:
    tamanho: int
    hash_completo: str
    arquivos: list[sqlite3.Row]
    manter: sqlite3.Row

    @property
    def recuperavel(self) -> int:
        return self.tamanho * (len(self.arquivos) - 1)

    @property
    def motivo(self) -> str:
        return f"mesmo tamanho ({self.tamanho} bytes) e mesmo hash BLAKE3 ({self.hash_completo[:12]}…)"


@dataclass
class ResultadoDuplicados:
    grupos: list[GrupoDuplicado] = field(default_factory=list)
    desatualizados: list[str] = field(default_factory=list)
    erros: list[str] = field(default_factory=list)

    @property
    def recuperavel(self) -> int:
        return sum(g.recuperavel for g in self.grupos)


def _sugerir_manter(arquivos: list[sqlite3.Row]) -> sqlite3.Row:
    """Sugere manter o mais antigo; empate → caminho mais curto."""
    return min(arquivos, key=lambda a: (a["criado_em"] or "", len(a["caminho"]), a["caminho"]))


def _ainda_igual(linha: sqlite3.Row) -> bool:
    """O arquivo no disco continua igual ao que está no índice?"""
    try:
        st = os.stat(linha["caminho"])
    except OSError:
        return False
    return st.st_size == linha["tamanho"] and st.st_mtime_ns == linha["modificado_ns"]


def encontrar_duplicados(
    indice: Indice,
    pasta: str | Path,
    *,
    hasher: Hasher | None = None,
    ao_progredir: Callable[[ProgressoHash], None] | None = None,
) -> ResultadoDuplicados:
    """Duplicados exatos em 3 etapas: tamanho → hash parcial → hash completo.

    Hashes já calculados (e ainda válidos) são reaproveitados do índice.
    Dois arquivos só são duplicados se o hash COMPLETO for igual (nunca por amostra).
    """
    hasher = hasher or Hasher()
    resultado = ResultadoDuplicados()
    agora = datetime.now().isoformat(timespec="seconds")

    # Etapa 1: tamanho (feita no SQL) + conferência de que o índice não está velho.
    candidatos = []
    for linha in indice.candidatos_duplicados(prefixo_da_pasta(pasta)):
        if _ainda_igual(linha):
            candidatos.append(linha)
        else:
            resultado.desatualizados.append(linha["caminho"])

    progresso = ProgressoHash(total=len(candidatos))
    parciais: dict[int, str] = {}
    completos: dict[int, str] = {}

    def avisar() -> None:
        progresso.bytes_lidos = hasher.bytes_lidos
        if ao_progredir:
            ao_progredir(progresso)

    # Etapa 2: hash parcial (começo do arquivo).
    for linha in candidatos:
        parcial, completo = linha["hash_parcial"], linha["hash_completo"]
        try:
            if parcial is None:
                parcial = hasher.parcial(linha["caminho"])
                if linha["tamanho"] <= TAMANHO_PARCIAL:
                    completo = parcial  # leu o arquivo inteiro
                indice.gravar_hashes(linha["id"], parcial, completo, agora)
        except OSError as erro:
            resultado.erros.append(f"{linha['caminho']}: {erro.strerror}")
            continue
        parciais[linha["id"]] = parcial
        if completo is not None:
            completos[linha["id"]] = completo
        progresso.feitos += 1
        if progresso.feitos % 25 == 0:
            avisar()

    por_parcial: dict[tuple[int, str], list[sqlite3.Row]] = defaultdict(list)
    for linha in candidatos:
        if linha["id"] in parciais:
            por_parcial[(linha["tamanho"], parciais[linha["id"]])].append(linha)

    # Etapa 3: hash completo, só para quem empatou no parcial.
    por_completo: dict[tuple[int, str], list[sqlite3.Row]] = defaultdict(list)
    for (tamanho, _), grupo in por_parcial.items():
        if len(grupo) < 2:
            continue
        for linha in grupo:
            completo = completos.get(linha["id"])
            if completo is None:
                try:
                    completo = hasher.completo(linha["caminho"])
                except OSError as erro:
                    resultado.erros.append(f"{linha['caminho']}: {erro.strerror}")
                    continue
                indice.gravar_hashes(linha["id"], None, completo, agora)
                avisar()
            por_completo[(tamanho, completo)].append(linha)

    indice.confirmar()

    for (tamanho, completo), arquivos in por_completo.items():
        if len(arquivos) > 1:
            resultado.grupos.append(GrupoDuplicado(tamanho, completo, arquivos, _sugerir_manter(arquivos)))
    resultado.grupos.sort(key=lambda g: g.recuperavel, reverse=True)

    progresso.terminou = True
    avisar()
    return resultado


# --- pesados e lixo -------------------------------------------------------


def pesados(indice: Indice, pasta: str | Path, limite: int = config.TOP_PESADOS) -> list[sqlite3.Row]:
    return indice.maiores(prefixo_da_pasta(pasta), limite)


def totais_por_categoria(indice: Indice, pasta: str | Path) -> list[sqlite3.Row]:
    return indice.totais_por_categoria(prefixo_da_pasta(pasta))


@dataclass
class Lixo:
    vazios: list[sqlite3.Row]
    temporarios: list[sqlite3.Row]

    @property
    def recuperavel(self) -> int:
        return sum(l["tamanho"] for l in self.temporarios)


def _temporarios(indice: Indice, prefixo: str) -> list[sqlite3.Row]:
    return indice.temporarios(prefixo, config.TEMP_EXTENSOES, config.TEMP_PREFIXOS, config.TEMP_NOMES)


def lixo(indice: Indice, pasta: str | Path) -> Lixo:
    prefixo = prefixo_da_pasta(pasta)
    return Lixo(vazios=indice.arquivos_vazios(prefixo), temporarios=_temporarios(indice, prefixo))


def extensao_errada(indice: Indice, pasta: str | Path) -> list[sqlite3.Row]:
    """Arquivos cujo conteúdo não combina com a extensão. Temporários ficam de fora (já são lixo).

    A regra é aplicada agora sobre `tipo_real` + `extensao`, então melhorias em
    `tipos.extensao_confere` valem sem precisar reindexar.
    """
    prefixo = prefixo_da_pasta(pasta)
    temporarios = {l["id"] for l in _temporarios(indice, prefixo)}
    return [
        l for l in indice.todos(prefixo)
        if l["id"] not in temporarios and l["tipo_real"]
        and not extensao_confere(l["tipo_real"], l["extensao"])
    ]


# --- pastas vazias (lê o disco, porque o índice não guarda pastas) ---------


def pastas_vazias(pasta: str | Path, bloqueios: Bloqueios | None = None) -> list[str]:
    """Pastas sem nenhum arquivo, nem em subpastas. Lista só a de cima de cada árvore vazia.

    Pastas bloqueadas, links e pastas que não dá para ler contam como "não vazias"
    (na dúvida, não sugerimos nada).
    """
    bloqueios = bloqueios or Bloqueios()
    encontradas: list[str] = []

    def vazia(caminho: str) -> bool:
        try:
            with os.scandir(caminho) as it:
                entradas = list(it)
        except OSError:
            return False
        subpastas_vazias = []
        tudo_vazio = True
        for e in entradas:
            eh_juncao = getattr(e, "is_junction", None)
            if e.is_symlink() or (eh_juncao and eh_juncao()):
                tudo_vazio = False
            elif e.is_dir(follow_symlinks=False):
                if bloqueios.bloqueada(e.path) or not vazia(e.path):
                    tudo_vazio = False
                else:
                    subpastas_vazias.append(e.path)
            else:
                tudo_vazio = False
        if not tudo_vazio:
            encontradas.extend(subpastas_vazias)  # as vazias de dentro aparecem sozinhas
        return tudo_vazio

    raiz = str(Path(pasta).resolve())
    if vazia(raiz):
        # A raiz inteira está vazia: listamos as subpastas de primeiro nível, não a raiz.
        with os.scandir(raiz) as it:
            encontradas.extend(e.path for e in it if e.is_dir(follow_symlinks=False))
    return sorted(encontradas)
