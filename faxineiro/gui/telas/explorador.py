"""Explorador: pastas do índice, lista paginada, busca por nome e descrição, detalhes com miniatura."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSplitter,
    QTableView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...formato import formatar_bytes
from ..modelos import ModeloArquivos

PAPEL_CAMINHO = Qt.ItemDataRole.UserRole


class TelaExplorador(QWidget):
    def __init__(self, amb) -> None:
        super().__init__()
        self.amb = amb
        self.pasta_atual: Path = amb.pasta
        layout = QHBoxLayout(self)
        divisor = QSplitter()

        self.arvore = QTreeWidget()
        self.arvore.setHeaderLabels(["Pasta", "Tamanho"])
        self.arvore.setColumnWidth(0, 200)
        self.arvore.itemExpanded.connect(self._expandir)
        self.arvore.currentItemChanged.connect(self._pasta_escolhida)
        divisor.addWidget(self.arvore)

        centro = QWidget()
        cl = QVBoxLayout(centro)
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Buscar por nome ou descrição (em todas as subpastas)...")
        self._espera = QTimer(self, singleShot=True, interval=350)  # busca só quando parar de digitar
        self._espera.timeout.connect(self._buscar)
        self.busca.textChanged.connect(lambda _: self._espera.start())
        cl.addWidget(self.busca)
        self.modelo = ModeloArquivos()
        self.tabela = QTableView()
        self.tabela.setModel(self.modelo)
        self.tabela.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.tabela.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.tabela.verticalHeader().hide()
        self.tabela.horizontalHeader().setStretchLastSection(True)
        self.tabela.setColumnWidth(0, 220)
        self.tabela.selectionModel().currentRowChanged.connect(self._arquivo_escolhido)
        cl.addWidget(self.tabela)
        divisor.addWidget(centro)

        detalhes = QWidget()
        dl = QVBoxLayout(detalhes)
        self.miniatura = QLabel("")
        self.miniatura.setFixedSize(110, 110)
        self.miniatura.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dl.addWidget(self.miniatura)
        self.form = QFormLayout()
        self.campos = {}
        for nome in ("Nome", "Pasta", "Tipo real", "Tamanho", "Criado", "Modificado", "Hash", "Descrição", "Origem"):
            rotulo = QLabel("")
            rotulo.setWordWrap(True)
            rotulo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.campos[nome] = rotulo
            self.form.addRow(nome + ":", rotulo)
        dl.addLayout(self.form)
        dl.addStretch(1)
        divisor.addWidget(detalhes)
        divisor.setSizes([230, 600, 300])
        layout.addWidget(divisor)

        self.amb.miniaturas.pronta.connect(self._miniatura_chegou)
        self._caminho_mostrado = ""
        self.recarregar_arvore()

    def ao_mostrar(self) -> None:
        self.recarregar_arvore()

    # --- árvore (filhas carregadas só ao expandir) ---------------------------------

    def _item(self, pai, pasta: Path, nome: str, bytes_: int) -> QTreeWidgetItem:
        item = QTreeWidgetItem(pai, [nome, formatar_bytes(bytes_ or 0)])
        item.setData(0, PAPEL_CAMINHO, str(pasta))
        QTreeWidgetItem(item, ["…"])  # marcador: "tem filhas, carregue quando abrir"
        return item

    def recarregar_arvore(self) -> None:
        self.arvore.clear()
        raiz = self._item(self.arvore, self.amb.pasta, self.amb.pasta.name, 0)
        raiz.setExpanded(True)
        self.arvore.setCurrentItem(raiz)

    def _expandir(self, item: QTreeWidgetItem) -> None:
        if item.childCount() == 1 and item.child(0).data(0, PAPEL_CAMINHO) is None:
            item.takeChild(0)
            pasta = Path(item.data(0, PAPEL_CAMINHO))
            for sub in self.amb.leitura.subpastas(pasta):
                self._item(item, pasta / sub["nome"], sub["nome"], sub["bytes"])

    def _pasta_escolhida(self, item: QTreeWidgetItem | None, _anterior=None) -> None:
        if item is None or item.data(0, PAPEL_CAMINHO) is None:
            return
        self.pasta_atual = Path(item.data(0, PAPEL_CAMINHO))
        if not self.busca.text().strip():
            leitura = self.amb.leitura
            pasta = self.pasta_atual
            self.modelo.trocar_fonte(lambda lim, off: leitura.arquivos_da_pasta(pasta, lim, off))

    def _buscar(self) -> None:
        termo = self.busca.text().strip()
        if not termo:
            self._pasta_escolhida(self.arvore.currentItem())
            return
        leitura, base = self.amb.leitura, self.amb.pasta
        self.modelo.trocar_fonte(lambda lim, off: leitura.buscar_texto(base, termo, lim, off))

    # --- detalhes ------------------------------------------------------------------

    def _arquivo_escolhido(self, atual, _anterior=None) -> None:
        if not atual.isValid():
            return
        l = self.modelo.linha(atual.row())
        p = Path(l["caminho"])
        valores = {
            "Nome": l["nome"], "Pasta": str(p.parent), "Tipo real": f"{l['tipo_real']} ({l['categoria']})"
            + ("" if l["extensao_confere"] else " — extensão não confere!"),
            "Tamanho": formatar_bytes(l["tamanho"]), "Criado": (l["criado_em"] or "").replace("T", " "),
            "Modificado": (l["modificado_em"] or "").replace("T", " "),
            "Hash": (l["hash_completo"][:16] + "…") if l["hash_completo"] else "(ainda não calculado)",
            "Descrição": l["descricao"] or "(sem descrição)",
            "Origem": {"ia": "IA", "ia_visao": "IA (visão)", "regras": "regras"}.get(l["descricao_origem"], "—")
            + (" — marcado para revisar" if l["revisar"] else ""),
        }
        for nome, valor in valores.items():
            self.campos[nome].setText(str(valor))
        self.miniatura.clear()
        self._caminho_mostrado = l["caminho"]
        if l["categoria"] == "imagem":
            self.amb.miniaturas.pedir(l["caminho"])

    def _miniatura_chegou(self, caminho: str, pix: QPixmap) -> None:
        if caminho == self._caminho_mostrado:
            self.miniatura.setPixmap(pix)
