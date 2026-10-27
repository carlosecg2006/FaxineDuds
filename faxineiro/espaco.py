"""Quanto do disco o índice explica, e quanto fica "não explicado" (sistema, pastas bloqueadas...).

Só lê: o tamanho usado vem do Windows (`shutil.disk_usage`), o explicado vem do índice, e os
arquivos de sistema conhecidos (paginação, hibernação, swap) vêm da LISTAGEM da raiz — nada é
aberto, e as pastas bloqueadas nunca são percorridas.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .indice import Indice

ARQUIVOS_DE_SISTEMA = {
    "pagefile.sys": "arquivo de paginação (memória virtual)",
    "hiberfil.sys": "arquivo de hibernação",
    "swapfile.sys": "arquivo de troca dos apps da Loja",
}


@dataclass
class EspacoUnidade:
    unidade: str  # ex.: "C:\\"
    total: int
    usado: int
    livre: int
    explicado: int  # soma dos arquivos que estão no índice nessa unidade
    sistema: dict[str, int] = field(default_factory=dict)  # arquivos conhecidos da raiz
    backups: dict[str, int] = field(default_factory=dict)  # rótulo → bytes (ex.: FileHistory)
    # Pastas de programa (.minecraft, .vscode...): já contam no "explicado"; aqui só o total de cada.
    programas: dict[str, int] = field(default_factory=dict)

    @property
    def sistema_total(self) -> int:
        return sum(self.sistema.values())

    @property
    def backups_total(self) -> int:
        return sum(self.backups.values())

    @property
    def nao_explicado(self) -> int:
        """Windows, Program Files, AppData, lixeira, pontos de restauração... (só o total)."""
        return max(self.usado - self.explicado - self.sistema_total - self.backups_total, 0)


def tamanho_da_pasta(pasta: str | Path) -> int:
    """Soma os tamanhos pela LISTAGEM das pastas (não abre nenhum arquivo, não segue atalhos)."""
    total, pilha = 0, [str(pasta)]
    while pilha:
        atual = pilha.pop()
        try:
            with os.scandir(atual) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            pilha.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def backups_do_windows(raiz: str | Path) -> dict[str, int]:
    """Pastas de backup do Windows na raiz da unidade (ex.: D:\\FileHistory), só com o total."""
    achados: dict[str, int] = {}
    try:
        with os.scandir(raiz) as it:
            for e in it:
                rotulo = next((r for nome, r in config.BACKUPS_DO_WINDOWS.items()
                               if e.name.casefold() == nome.casefold()), None)
                if rotulo and e.is_dir(follow_symlinks=False):
                    achados[rotulo] = achados.get(rotulo, 0) + tamanho_da_pasta(e.path)
    except OSError:
        pass
    return achados


def arquivos_de_sistema(raiz: str | Path) -> dict[str, int]:
    """Tamanho de pagefile/hiberfil/swapfile pela listagem da pasta (não abre os arquivos)."""
    achados: dict[str, int] = {}
    try:
        with os.scandir(raiz) as it:
            for e in it:
                if e.name.casefold() in ARQUIVOS_DE_SISTEMA:
                    try:
                        achados[e.name.casefold()] = e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
    except OSError:
        pass
    return achados


def calcular(
    indice: Indice,
    unidade: str,
    uso: Callable[[str], tuple[int, int, int]] = shutil.disk_usage,
    sistema: Callable[[str], dict[str, int]] = arquivos_de_sistema,
    backups: Callable[[str], dict[str, int]] = backups_do_windows,
) -> EspacoUnidade:
    raiz = str(Path(unidade).anchor or unidade)
    total, usado, livre = uso(raiz)
    return EspacoUnidade(unidade=raiz, total=total, usado=usado, livre=livre,
                         explicado=indice.soma_por_prefixo(raiz), sistema=sistema(raiz), backups=backups(raiz),
                         programas=indice.pastas_de_programa(raiz, config.PASTAS_DE_PROGRAMA))
