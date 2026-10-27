"""Operações no disco que aceitam caminhos com mais de 260 caracteres (Fase 7B).

Neste PC o Windows está com LongPathsEnabled = 0: um caminho normal só funciona até ~260
caracteres (pastas até ~248). Com o prefixo `\\\\?\\` o Windows aceita até ~32 mil, sem
precisar mudar o registro. O índice continua guardando o caminho normal; o prefixo só aparece
na hora de falar com o sistema (`no_disco`).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

PREFIXO = "\\\\?\\"
PREFIXO_UNC = "\\\\?\\UNC\\"


def no_disco(caminho: str | Path) -> str:
    """Caminho pronto para o Windows: absoluto e com `\\\\?\\` (não muda nada fora do Windows)."""
    texto = str(caminho)
    if os.name != "nt" or texto.startswith(PREFIXO):
        return texto
    texto = os.path.abspath(texto)  # o prefixo desliga a normalização: ".." e "/" precisam sair antes
    if texto.startswith("\\\\"):
        return PREFIXO_UNC + texto[2:]
    return PREFIXO + texto


def sem_prefixo(caminho: str) -> str:
    """O caminho como o usuário vê (e como fica no índice)."""
    if caminho.startswith(PREFIXO_UNC):
        return "\\\\" + caminho[len(PREFIXO_UNC):]
    if caminho.startswith(PREFIXO):
        return caminho[len(PREFIXO):]
    return caminho


def existe(caminho: str | Path) -> bool:
    return os.path.lexists(no_disco(caminho))


def eh_arquivo(caminho: str | Path) -> bool:
    return os.path.isfile(no_disco(caminho))


def eh_pasta(caminho: str | Path) -> bool:
    return os.path.isdir(no_disco(caminho))


def info(caminho: str | Path) -> os.stat_result:
    return os.stat(no_disco(caminho))


def tamanho(caminho: str | Path) -> int:
    return info(caminho).st_size


def renomear(origem: str | Path, destino: str | Path) -> None:
    """Mesma unidade: só troca o nome no índice do disco (instantâneo, não copia).
    `os.rename` nunca sobrescreve no Windows: se o destino existir, dá erro."""
    os.rename(no_disco(origem), no_disco(destino))


def criar_pastas(pasta: str | Path) -> None:
    os.makedirs(no_disco(pasta), exist_ok=True)


def remover_pasta_vazia(pasta: str | Path) -> None:
    os.rmdir(no_disco(pasta))  # rmdir só remove pasta VAZIA


def listar(pasta: str | Path) -> list[str]:
    return os.listdir(no_disco(pasta))


def percorrer(raiz: str | Path, de_baixo_para_cima: bool = False) -> Iterator[tuple[str, list[str], list[str]]]:
    """os.walk com caminhos longos; devolve os caminhos sem o prefixo."""
    for pasta, subpastas, arquivos in os.walk(no_disco(raiz), topdown=not de_baixo_para_cima):
        yield sem_prefixo(pasta), subpastas, arquivos


def abrir(caminho: str | Path, modo: str = "rb", **kw):
    return open(no_disco(caminho), modo, **kw)

