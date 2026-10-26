"""Tabela de arquivos que carrega AOS POUCOS: 200 linhas por vez, só quando a rolagem chega no fim."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from ..formato import formatar_bytes

TAMANHO_PAGINA = 200

Fonte = Callable[[int, int], list[sqlite3.Row]]  # (limite, offset) -> linhas


class ModeloArquivos(QAbstractTableModel):
    COLUNAS = ("Nome", "Tamanho", "Tipo", "Modificado", "Descrição")

    def __init__(self, fonte: Fonte | None = None, parent=None) -> None:
        super().__init__(parent)
        self._linhas: list[sqlite3.Row] = []
        self._fonte = fonte
        self._acabou = fonte is None

    def trocar_fonte(self, fonte: Fonte | None) -> None:
        self.beginResetModel()
        self._linhas = []
        self._fonte = fonte
        self._acabou = fonte is None
        self.endResetModel()
        if self.canFetchMore(QModelIndex()):
            self.fetchMore(QModelIndex())

    def linha(self, i: int) -> sqlite3.Row:
        return self._linhas[i]

    # --- carregamento aos poucos ------------------------------------------------

    def canFetchMore(self, parent: QModelIndex) -> bool:
        return not parent.isValid() and not self._acabou

    def fetchMore(self, parent: QModelIndex) -> None:
        if self._acabou or self._fonte is None:
            return
        pagina = self._fonte(TAMANHO_PAGINA, len(self._linhas))
        if len(pagina) < TAMANHO_PAGINA:
            self._acabou = True
        if pagina:
            inicio = len(self._linhas)
            self.beginInsertRows(QModelIndex(), inicio, inicio + len(pagina) - 1)
            self._linhas.extend(pagina)
            self.endInsertRows()

    # --- QAbstractTableModel ---------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._linhas)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLUNAS)

    def headerData(self, secao: int, orientacao, papel=Qt.ItemDataRole.DisplayRole):
        if papel == Qt.ItemDataRole.DisplayRole and orientacao == Qt.Orientation.Horizontal:
            return self.COLUNAS[secao]
        return None

    def data(self, indice: QModelIndex, papel=Qt.ItemDataRole.DisplayRole):
        if not indice.isValid():
            return None
        l = self._linhas[indice.row()]
        col = indice.column()
        if papel == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return l["nome"]
            if col == 1:
                return formatar_bytes(l["tamanho"])
            if col == 2:
                return f"{l['tipo_real'] or '?'} ({l['categoria'] or '?'})"
            if col == 3:
                return (l["modificado_em"] or "")[:16].replace("T", " ")
            if col == 4:
                return l["descricao"] or ""
        if papel == Qt.ItemDataRole.ToolTipRole:
            return l["caminho"]
        if papel == Qt.ItemDataRole.TextAlignmentRole and col == 1:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None
