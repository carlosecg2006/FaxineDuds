"""Janela principal: barra lateral com as 6 telas, barra de progresso com Cancelar e tema claro/escuro."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QStyleFactory,
    QWidget,
)

from ..config import CAMINHO_INDICE, PASTA_TESTE
from ..indice import Indice
from ..quarentena import Quarentena
from .miniaturas import CarregadorMiniaturas
from .tarefas import Contexto, GerenteTarefas


@dataclass
class Ambiente:
    """O que toda tela precisa: onde está o índice, qual pasta, e quem roda as tarefas."""

    caminho_indice: Path
    pasta: Path  # pasta que o app está cuidando (no desenvolvimento: a pasta_teste)
    limite: Path  # trava da regra 5: nada fora daqui é tocado
    gerente: GerenteTarefas
    leitura: Indice  # conexão da thread da janela, só para LER páginas pequenas
    miniaturas: CarregadorMiniaturas
    janela: "Janela | None" = None
    local_quarentena: Callable[[Path], Path] | None = None  # None = config.pasta_quarentena

    def abrir_indice(self) -> Indice:
        """Para usar DENTRO de uma tarefa: cada thread com a sua conexão."""
        return Indice(self.caminho_indice)

    def quarentena(self, indice: Indice) -> Quarentena:
        return Quarentena(indice, limite=self.limite, local=self.local_quarentena)

    def rodar(self, titulo: str, funcao, ao_terminar=None) -> bool:
        def falhou(msg: str) -> None:
            QMessageBox.critical(self.janela, titulo, f"Deu erro:\n{msg}")

        if self.gerente.iniciar(titulo, funcao, ao_terminar, falhou) is None:
            QMessageBox.information(self.janela, titulo, "Espere a operação atual terminar (ou cancele).")
            return False
        return True

    def mensagem(self, texto: str) -> None:
        if self.janela is not None:
            self.janela.statusBar().showMessage(texto, 8000)


def aplicar_tema(app: QApplication, escuro: bool) -> None:
    app.setStyle(QStyleFactory.create("Fusion"))
    if not escuro:
        app.setPalette(app.style().standardPalette())
        return
    p = QPalette()
    cores = {
        QPalette.ColorRole.Window: "#202124", QPalette.ColorRole.WindowText: "#e8eaed",
        QPalette.ColorRole.Base: "#17181a", QPalette.ColorRole.AlternateBase: "#26272b",
        QPalette.ColorRole.Text: "#e8eaed", QPalette.ColorRole.Button: "#2b2c30",
        QPalette.ColorRole.ButtonText: "#e8eaed", QPalette.ColorRole.Highlight: "#4e9af1",
        QPalette.ColorRole.HighlightedText: "#ffffff", QPalette.ColorRole.ToolTipBase: "#2b2c30",
        QPalette.ColorRole.ToolTipText: "#e8eaed", QPalette.ColorRole.PlaceholderText: "#9aa0a6",
    }
    for papel, cor in cores.items():
        p.setColor(papel, QColor(cor))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#6b6f75"))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#6b6f75"))
    app.setPalette(p)


class Janela(QMainWindow):
    def __init__(self, amb: Ambiente) -> None:
        super().__init__()
        from .telas import TELAS  # import aqui para evitar ciclo

        self.amb = amb
        amb.janela = self
        self.setWindowTitle(f"Faxineiro — {amb.pasta}")
        self.resize(1180, 760)

        centro = QWidget()
        layout = QHBoxLayout(centro)
        layout.setContentsMargins(0, 0, 0, 0)
        self.lateral = QListWidget()
        self.lateral.setFixedWidth(170)
        self.pilha = QStackedWidget()
        self.telas = []
        for nome, classe in TELAS:
            tela = classe(amb)
            self.telas.append(tela)
            self.lateral.addItem(nome)
            self.pilha.addWidget(tela)
        self.lateral.currentRowChanged.connect(self._trocar_tela)
        layout.addWidget(self.lateral)
        layout.addWidget(self.pilha, 1)
        self.setCentralWidget(centro)

        # Barra de status: texto, progresso e Cancelar (para toda operação longa).
        self.rotulo_tarefa = QLabel("")
        self.barra = QProgressBar()
        self.barra.setFixedWidth(260)
        self.barra.hide()
        self.botao_cancelar = QPushButton("Cancelar")
        self.botao_cancelar.hide()
        self.botao_cancelar.clicked.connect(amb.gerente.cancelar)
        self.statusBar().addPermanentWidget(self.rotulo_tarefa)
        self.statusBar().addPermanentWidget(self.barra)
        self.statusBar().addPermanentWidget(self.botao_cancelar)
        amb.gerente.comecou.connect(self._tarefa_comecou)
        amb.gerente.progresso.connect(self._tarefa_progresso)
        amb.gerente.acabou.connect(self._tarefa_acabou)

        menu = self.menuBar().addMenu("Exibir")
        self.acao_escuro = QAction("Tema escuro", self, checkable=True)
        self.acao_escuro.setChecked(QSettings("Faxineiro", "Faxineiro").value("tema_escuro", False, type=bool))
        self.acao_escuro.toggled.connect(self._mudar_tema)
        menu.addAction(self.acao_escuro)

        self.lateral.setCurrentRow(0)
        self._recuperar()

    def _recuperar(self) -> None:
        """Como na linha de comando: ao abrir, termina ou marca o que ficou pela metade."""
        mensagens = self.amb.quarentena(self.amb.leitura).recuperar_diario()
        if mensagens:
            QMessageBox.information(self, "Diário de operações",
                                    "Encontrei operações interrompidas e cuidei delas:\n\n" + "\n".join(mensagens))

    def _trocar_tela(self, i: int) -> None:
        self.pilha.setCurrentIndex(i)
        tela = self.telas[i]
        if hasattr(tela, "ao_mostrar"):
            tela.ao_mostrar()

    def _mudar_tema(self, escuro: bool) -> None:
        QSettings("Faxineiro", "Faxineiro").setValue("tema_escuro", escuro)
        aplicar_tema(QApplication.instance(), escuro)

    def _tarefa_comecou(self, titulo: str) -> None:
        self.rotulo_tarefa.setText(titulo + "...")
        self.barra.setRange(0, 0)  # "ocupado" até saber o total
        self.barra.show()
        self.botao_cancelar.show()
        self.botao_cancelar.setEnabled(True)

    def _tarefa_progresso(self, feitos: int, total: int, texto: str) -> None:
        if total > 0:
            self.barra.setRange(0, total)
            self.barra.setValue(min(feitos, total))
        if texto:
            self.rotulo_tarefa.setText(texto)

    def _tarefa_acabou(self) -> None:
        self.barra.hide()
        self.botao_cancelar.hide()
        self.rotulo_tarefa.setText("")

    def closeEvent(self, evento) -> None:
        if self.amb.gerente.ocupado:
            self.amb.gerente.cancelar()
            self.amb.gerente.esperar(5000)
        self.amb.leitura.fechar()
        super().closeEvent(evento)


def criar_ambiente(caminho_indice: Path = CAMINHO_INDICE, pasta: Path = PASTA_TESTE,
                   limite: Path = PASTA_TESTE) -> Ambiente:
    return Ambiente(caminho_indice=Path(caminho_indice), pasta=Path(pasta).resolve(),
                    limite=Path(limite).resolve(), gerente=GerenteTarefas(),
                    leitura=Indice(caminho_indice), miniaturas=CarregadorMiniaturas())


def principal(argv: list[str] | None = None) -> int:
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("Faxineiro")
    aplicar_tema(app, QSettings("Faxineiro", "Faxineiro").value("tema_escuro", False, type=bool))
    janela = Janela(criar_ambiente())
    janela.show()
    return app.exec()


__all__ = ["Ambiente", "Contexto", "Janela", "aplicar_tema", "criar_ambiente", "principal"]
