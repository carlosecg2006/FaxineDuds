"""Janela principal: barra lateral com as telas, barra de progresso com Cancelar e tema claro/escuro."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QStyleFactory,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..config import AREAS_DE_LEITURA, CAMINHO_INDICE, PASTA_TESTE, Bloqueios, area_de
from ..indice import Indice
from ..quarentena import Quarentena
from .miniaturas import CarregadorMiniaturas
from .tarefas import Contexto, GerenteTarefas


@dataclass
class Ambiente:
    """O que toda tela precisa: onde está o índice, qual pasta, e quem roda as tarefas."""

    caminho_indice: Path
    pasta: Path  # pasta que o app está mostrando (pasta_teste, C:\Users\..., D:\ ou uma de dentro)
    limite: Path  # a pasta_teste: com o modo PC real desligado, nada fora daqui é tocado (regra 5)
    gerente: GerenteTarefas
    leitura: Indice  # conexão da thread da janela, só para LER páginas pequenas
    miniaturas: CarregadorMiniaturas
    janela: "Janela | None" = None
    local_quarentena: Callable[[Path], Path] | None = None  # None = config.pasta_quarentena
    pc_real: bool = False  # Fase 7B: começa SEMPRE desligado; liga pela janela, digitando PC REAL
    areas_pc: tuple[Path, ...] = AREAS_DE_LEITURA  # o que o modo PC real libera (os testes trocam)
    unidade: Callable[[Path], str] | None = None  # None = letra da unidade (os testes simulam duas)

    @property
    def areas(self) -> tuple[Path, ...]:
        """Onde as ações podem mudar o disco agora (Quarentena, conversor, mover de unidade)."""
        return (self.limite, *self.areas_pc) if self.pc_real else (self.limite,)

    @property
    def pastas(self) -> tuple[Path, ...]:
        """Pastas para ver/analisar (ler é sempre permitido nelas, com o modo ligado ou não)."""
        return (self.limite, *self.areas_pc)

    def abrir_indice(self) -> Indice:
        """Para usar DENTRO de uma tarefa: cada thread com a sua conexão."""
        return Indice(self.caminho_indice)

    def quarentena(self, indice: Indice) -> Quarentena:
        return Quarentena(indice, limite=self.areas, local=self.local_quarentena, unidade=self.unidade)

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
        self.resize(1180, 760)

        # Fase 7B: escolher a pasta (ler é sempre permitido) e o interruptor do modo PC real.
        barra = QToolBar("Pasta")
        barra.setMovable(False)
        barra.addWidget(QLabel(" Pasta: "))
        self.seletor = QComboBox()
        self.seletor.setMinimumWidth(320)
        for pasta in amb.pastas:
            self.seletor.addItem(str(pasta), str(pasta))
        self.seletor.addItem("Outra pasta…", None)
        self.seletor.setCurrentIndex(max(0, self.seletor.findData(str(amb.pasta))))
        self.seletor.activated.connect(self._seletor_escolhido)
        barra.addWidget(self.seletor)
        self.addToolBar(barra)

        self.faixa = QLabel("MODO PC REAL LIGADO — as ações mexem nos arquivos de verdade "
                            "(pastas bloqueadas, de programa, pastas-bloco e da nuvem continuam protegidas)")
        self.faixa.setStyleSheet("background:#c62828;color:white;font-weight:bold;padding:6px;")
        self.faixa.setWordWrap(True)
        self.faixa.hide()

        centro = QWidget()
        coluna = QVBoxLayout(centro)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(0)
        coluna.addWidget(self.faixa)
        linha = QWidget()
        coluna.addWidget(linha, 1)
        layout = QHBoxLayout(linha)
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

        seguranca = self.menuBar().addMenu("Segurança")
        self.acao_pc_real = QAction("Modo PC real (mexer fora da pasta_teste)", self, checkable=True)
        self.acao_pc_real.toggled.connect(self._pc_real_mudou)
        seguranca.addAction(self.acao_pc_real)

        self.lateral.setCurrentRow(0)
        self._atualizar_titulo()
        self._recuperar()

    # --- modo PC real e pasta ---------------------------------------------------------

    def ligar_pc_real(self, ligar: bool, perguntar_texto=None) -> bool:
        """Ligar pede para digitar PC REAL; desligar não pergunta nada. Não fica salvo:
        toda vez que o app abre, começa desligado."""
        if ligar and not self.amb.pc_real:
            perguntar_texto = perguntar_texto or (lambda: QInputDialog.getText(
                self, "Ligar o modo PC real",
                "Com o modo PC real, quarentena, organizar, converter e mover para outra unidade\n"
                f"passam a mexer em {', '.join(str(a) for a in self.amb.areas_pc)}.\n"
                "Pastas bloqueadas, de programa, pastas-bloco, da nuvem e backups continuam proibidas.\n"
                "Tudo continua com prévia, confirmação e desfazer.\n\nDigite PC REAL para ligar:"))
            texto, ok = perguntar_texto()
            if not ok or texto.strip() != "PC REAL":
                self.acao_pc_real.blockSignals(True)
                self.acao_pc_real.setChecked(False)
                self.acao_pc_real.blockSignals(False)
                self.amb.mensagem("Modo PC real continua desligado.")
                return False
        self.amb.pc_real = ligar
        self.acao_pc_real.blockSignals(True)
        self.acao_pc_real.setChecked(ligar)
        self.acao_pc_real.blockSignals(False)
        self.faixa.setVisible(ligar)
        self._atualizar_titulo()
        self.amb.mensagem("Modo PC real LIGADO." if ligar else "Modo PC real desligado: só a pasta_teste.")
        return True

    def _pc_real_mudou(self, ligado: bool) -> None:
        self.ligar_pc_real(ligado)

    def _atualizar_titulo(self) -> None:
        self.setWindowTitle(f"Faxineiro — {self.amb.pasta}" + ("  [MODO PC REAL]" if self.amb.pc_real else ""))

    def _seletor_escolhido(self, i: int) -> None:
        pasta = self.seletor.itemData(i)
        if pasta is None:
            pasta = QFileDialog.getExistingDirectory(self, "Escolher pasta", str(self.amb.pasta))
            if not pasta:
                self.seletor.setCurrentIndex(max(0, self.seletor.findData(str(self.amb.pasta))))
                return
        self.trocar_pasta(Path(pasta))

    def trocar_pasta(self, pasta: Path) -> bool:
        """Muda a pasta que as telas mostram. Ler é permitido na pasta_teste e nas áreas do PC real."""
        pasta = Path(pasta).resolve()
        area = area_de(pasta, self.amb.pastas)
        if area is None or any(Bloqueios().bloqueada(p) for p in (pasta, *pasta.parents) if area in p.parents):
            QMessageBox.warning(self, "Pasta", f"Não posso abrir {pasta} (fora das áreas ou pasta bloqueada).")
            self.seletor.setCurrentIndex(max(0, self.seletor.findData(str(self.amb.pasta))))
            return False
        self.amb.pasta = pasta
        if self.seletor.findData(str(pasta)) < 0:
            self.seletor.insertItem(self.seletor.count() - 1, str(pasta), str(pasta))
        self.seletor.setCurrentIndex(self.seletor.findData(str(pasta)))
        self._atualizar_titulo()
        for tela in self.telas:
            if hasattr(tela, "pasta_mudou"):
                tela.pasta_mudou()
        return True

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
        # Temporizadores parados ANTES de fechar o índice: senão a busca do Explorador (350 ms
        # depois da última tecla) dispara com a conexão já fechada — ou com a janela já destruída.
        for tela in self.telas:
            if hasattr(tela, "encerrar"):
                tela.encerrar()
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
