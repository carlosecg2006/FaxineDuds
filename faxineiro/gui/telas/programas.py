"""Programas (Fase 7C.2): programas e jogos instalados, com tamanho e último sinal de uso.

"Desinstalar" só ABRE o desinstalador oficial do programa (o Faxineiro não apaga nada)."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import programas
from ...formato import formatar_bytes
from ..dialogos import rotulo_flexivel
from ..sistema import mostrar_na_pasta

ORDEM = Qt.ItemDataRole.UserRole  # valor usado para ordenar (número ou data)
COLUNAS = ["Programa", "Tamanho", "Último sinal de uso", "Instalado em", "Origem", "Editora"]


class _Celula(QTableWidgetItem):
    """Ordena pelo valor guardado (tamanho em bytes, data ISO), não pelo texto."""

    def __lt__(self, outra) -> bool:
        a, b = self.data(ORDEM), outra.data(ORDEM)
        if a is not None and b is not None:
            return a < b
        return super().__lt__(outra)


def _data_br(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else ""


def _ha_quanto(iso: str | None, hoje: date | None = None) -> str:
    if not iso:
        return ""
    dias = ((hoje or date.today()) - date.fromisoformat(iso)).days
    if dias <= 0:
        return "hoje"
    if dias < 60:
        return f"há {dias} dias"
    return f"há {dias // 30} meses" if dias < 730 else f"há {dias // 365} anos"


class TelaProgramas(QWidget):
    def __init__(self, amb) -> None:
        super().__init__()
        self.amb = amb
        self.listar = programas.listar  # os testes trocam por uma lista falsa
        self.abrir = programas._shell  # quem abre o desinstalador (os testes trocam por um falso)
        self.lista: list[programas.Programa] = []
        layout = QVBoxLayout(self)

        topo = QHBoxLayout()
        self.resumo = rotulo_flexivel("<b>Programas e jogos instalados</b><br>Clique em <b>Atualizar lista</b> "
                                      "(só lê o registro do Windows, a Steam e o CurseForge).")
        topo.addWidget(self.resumo, 1)
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Filtrar pelo nome…")
        self.busca.textChanged.connect(self._filtrar)
        topo.addWidget(self.busca)
        self.botao_atualizar = QPushButton("Atualizar lista")
        self.botao_atualizar.clicked.connect(self.atualizar)
        topo.addWidget(self.botao_atualizar)
        layout.addLayout(topo)

        self.tabela = QTableWidget(0, len(COLUNAS))
        self.tabela.setHorizontalHeaderLabels(COLUNAS)
        self.tabela.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tabela.verticalHeader().hide()
        self.tabela.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabela.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabela.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.tabela.setSortingEnabled(True)
        layout.addWidget(self.tabela, 1)

        baixo = QHBoxLayout()
        self.botao_desinstalar = QPushButton("Desinstalar…")
        self.botao_desinstalar.setToolTip("Abre o desinstalador OFICIAL do programa (o mesmo das Configurações)")
        self.botao_desinstalar.clicked.connect(self.desinstalar)
        self.botao_pasta = QPushButton("Mostrar a pasta")
        self.botao_pasta.clicked.connect(self.mostrar_pasta)
        self.botao_loja = QPushButton("Apps da Microsoft Store…")
        self.botao_loja.setToolTip("Os apps da Loja são desinstalados pelas Configurações do Windows")
        self.botao_loja.clicked.connect(lambda: programas.abrir_aplicativos_da_loja(self.abrir))
        for b in (self.botao_desinstalar, self.botao_pasta):
            baixo.addWidget(b)
        baixo.addStretch(1)
        baixo.addWidget(self.botao_loja)
        layout.addLayout(baixo)
        nota = QLabel("\"Último sinal de uso\": <i>aberto</i> = a última vez que o Windows registrou o programa "
                      "abrindo (Menu Iniciar/atalhos) ou a Steam/CurseForge; <i>pasta mudou</i> = o arquivo mais "
                      "novo da pasta (pode ser só uma atualização). É uma pista, não uma certeza.")
        nota.setWordWrap(True)
        layout.addWidget(nota)

    def atualizar(self) -> bool:
        def trabalho(ctx):
            return self.listar(parar=ctx.parar, ao_progredir=lambda n, total, nome: ctx.avisar(
                n, total, f"Lendo os programas: {nome}"))

        def pronto(lista) -> None:
            self.mostrar(lista)
            self.amb.mensagem(f"{len(lista)} programas e jogos. Nada foi alterado.")

        return self.amb.rodar("Lendo os programas instalados", trabalho, pronto)

    def mostrar(self, lista: list[programas.Programa]) -> None:
        self.lista = lista
        self.tabela.setSortingEnabled(False)
        self.tabela.setRowCount(len(lista))
        for linha, p in enumerate(lista):
            uso, fonte = p.sinal_de_uso
            nome = p.nome + ("  (pasta não encontrada)" if not p.pasta_existe else "")
            valores = [
                (nome, p.nome.casefold()),
                (formatar_bytes(p.tamanho) if p.tamanho is not None else "?", p.tamanho if p.tamanho is not None else -1),
                (f"{fonte} {_ha_quanto(uso)} ({_data_br(uso)})" if uso else "sem sinal", uso or ""),
                (_data_br(p.instalado_em), p.instalado_em or ""),
                (p.origem, p.origem),
                (p.editora, p.editora.casefold()),
            ]
            for coluna, (texto, ordem) in enumerate(valores):
                celula = _Celula(texto)
                celula.setData(ORDEM, ordem)
                if coluna == 0:
                    celula.setData(Qt.ItemDataRole.UserRole + 1, linha)
                    celula.setToolTip(p.pasta or "")
                if coluna == 1:
                    celula.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.tabela.setItem(linha, coluna, celula)
        self.tabela.setSortingEnabled(True)
        self.tabela.sortItems(1, Qt.SortOrder.DescendingOrder)
        total = sum(p.tamanho or 0 for p in lista)
        sumidos = sum(1 for p in lista if not p.pasta_existe)
        self.resumo.setText(f"<b>{len(lista)} programas e jogos</b>, {formatar_bytes(total)} no total."
                            + (f" {sumidos} com a pasta não encontrada (unidade desconectada, como o E:, "
                               "ou sobra de desinstalação)." if sumidos else ""))
        self._filtrar(self.busca.text())

    def _filtrar(self, texto: str) -> None:
        texto = texto.casefold().strip()
        for linha in range(self.tabela.rowCount()):
            item = self.tabela.item(linha, 0)
            self.tabela.setRowHidden(linha, bool(texto) and texto not in (item.text().casefold() if item else ""))

    def selecionado(self) -> programas.Programa | None:
        linhas = self.tabela.selectionModel().selectedRows()
        if not linhas:
            return None
        item = self.tabela.item(linhas[0].row(), 0)
        return self.lista[item.data(Qt.ItemDataRole.UserRole + 1)]

    def mostrar_pasta(self) -> None:
        p = self.selecionado()
        if p is None or not p.pasta or not p.pasta_existe:
            self.amb.mensagem("Selecione um programa com pasta conhecida.")
            return
        mostrar_na_pasta(p.pasta)

    def desinstalar(self, confirmar=None) -> bool:
        p = self.selecionado()
        if p is None:
            self.amb.mensagem("Selecione um programa.")
            return False
        if not p.desinstalador:
            QMessageBox.information(self, "Desinstalar", p.como or "Este programa não tem desinstalador registrado.")
            return False
        onde = "a Steam" if p.desinstalador.startswith("steam://") else "o desinstalador oficial"
        texto = (f"Desinstalar <b>{p.nome}</b>"
                 + (f" ({formatar_bytes(p.tamanho)})" if p.tamanho else "") + f"?<br><br>"
                 f"O Faxineiro vai abrir {onde} deste programa. Siga as telas dele; o Windows pode pedir "
                 "administrador. O Faxineiro não apaga nada por conta própria.<br><br>"
                 "Sobras que o desinstalador deixar (no AppData, por exemplo) o Detetive de pastas vai mostrar.")
        confirmar = confirmar or (lambda: QMessageBox.question(self, "Desinstalar", texto)
                                  == QMessageBox.StandardButton.Yes)
        if not confirmar():
            self.amb.mensagem("Cancelado. Nada foi aberto.")
            return False
        try:
            chamado = programas.desinstalar(p, self.abrir)
        except (OSError, ValueError) as erro:
            QMessageBox.warning(self, "Desinstalar", str(erro))
            return False
        self.amb.mensagem(f"Desinstalador aberto ({chamado}). Depois, clique em Atualizar lista.")
        return True
