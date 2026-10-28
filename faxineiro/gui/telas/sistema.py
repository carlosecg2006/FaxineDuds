"""Sistema (Fase 7C.1): o que ocupa Windows, Program Files, ProgramData e AppData — só mostra."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import config, sistema
from ...formato import formatar_bytes, numero, relativo
from ..dialogos import rotulo_flexivel
from ..sistema import mostrar_na_pasta

CORES = {sistema.SEGURO: "#2e7d32", sistema.DESINSTALADOR: "#ef6c00", sistema.NAO_MEXA: "#c62828"}
CAMINHO = Qt.ItemDataRole.UserRole


class TelaSistema(QWidget):
    def __init__(self, amb) -> None:
        super().__init__()
        self.amb = amb
        self.pasta_dados = Path(amb.caminho_indice).parent  # a medição fica junto do índice (dados/)
        self.medir = sistema.medir_sistema  # os testes trocam por uma unidade falsa
        layout = QVBoxLayout(self)

        topo = QHBoxLayout()
        self.resumo = rotulo_flexivel()
        topo.addWidget(self.resumo, 1)
        self.unidade = QComboBox()
        for u in sorted({config.UNIDADE_DO_SISTEMA.upper(), *(Path(a).drive.upper() for a in config.AREAS_DE_LEITURA)}):
            if u:
                self.unidade.addItem(u, u)
        self.unidade.currentIndexChanged.connect(lambda _: self.carregar())
        topo.addWidget(self.unidade)
        self.botao_medir = QPushButton("Medir agora")
        self.botao_medir.setToolTip("Lê o tamanho das pastas de sistema (não abre nem muda nenhum arquivo)")
        self.botao_medir.clicked.connect(self.medir_agora)
        topo.addWidget(self.botao_medir)
        layout.addLayout(topo)

        self.arvore = QTreeWidget()
        self.arvore.setHeaderLabels(["Pasta", "Tamanho", "Selo", "O que é", "Como limpar"])
        self.arvore.setColumnWidth(0, 300)
        self.arvore.setColumnWidth(1, 80)
        self.arvore.setColumnWidth(2, 140)
        self.arvore.setColumnWidth(3, 380)
        self.arvore.itemDoubleClicked.connect(self._mostrar_no_explorador)
        layout.addWidget(self.arvore, 1)
        nota = QLabel("Só mostra: o Faxineiro nunca apaga nada dentro do Windows ou de Program Files. "
                      "Windows e WinSxS parecem maiores do que são (os mesmos arquivos vistos em dois lugares). "
                      "Clique duplo abre a pasta no Explorador do Windows.")
        nota.setWordWrap(True)
        layout.addWidget(nota)
        self.carregar()

    def ao_mostrar(self) -> None:
        self.carregar()

    def _arquivo(self) -> Path:
        return sistema.arquivo_salvo(self.unidade.currentData() or config.UNIDADE_DO_SISTEMA, self.pasta_dados)

    def carregar(self) -> None:
        rx = sistema.carregar(self._arquivo())
        self.mostrar(rx)

    def mostrar(self, rx: sistema.RaioXSistema | None) -> None:
        self.arvore.clear()
        if rx is None:
            self.resumo.setText(f"<b>Raio-X do sistema — {self.unidade.currentData()}</b><br>"
                                "Ainda não medido. Clique em <b>Medir agora</b> (leva alguns minutos; só lê).")
            return
        quando = rx.medido_em.replace("T", " ")[:16]
        self.resumo.setText(f"<b>Raio-X do sistema — {rx.unidade}</b> (medido em {quando})<br>"
                            f"{formatar_bytes(rx.total)} em pastas de sistema, de {formatar_bytes(rx.usado)} usados "
                            f"({numero(rx.pastas_lidas)} pastas lidas).")
        for item in rx.itens:
            self._adicionar(self.arvore, item, None)

    def _adicionar(self, pai, item: sistema.Item, caminho_pai: str | None) -> None:
        nome = relativo(item.caminho, Path(caminho_pai)) if caminho_pai else item.caminho
        if item.sem_permissao:
            nome += "  (sem permissão em parte)"
        como = "" if item.selo == sistema.NAO_MEXA and item.como in ("", "Não mexa") else item.como
        linha = QTreeWidgetItem(pai, [nome, formatar_bytes(item.tamanho), item.selo, item.explicacao, como])
        linha.setForeground(2, QColor(CORES[item.selo]))
        linha.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        linha.setToolTip(3, item.explicacao)
        linha.setToolTip(4, como)
        linha.setData(0, CAMINHO, item.caminho)
        for f in item.filhos:
            self._adicionar(linha, f, item.caminho)

    def _mostrar_no_explorador(self, linha: QTreeWidgetItem, _coluna: int) -> None:
        mostrar_na_pasta(linha.data(0, CAMINHO))

    def medir_agora(self) -> bool:
        unidade = self.unidade.currentData() or config.UNIDADE_DO_SISTEMA
        destino = self._arquivo()

        def trabalho(ctx):
            rx = self.medir(unidade, parar=ctx.parar, ao_progredir=lambda p: ctx.avisar(
                p.pastas, 0, f"Medindo o sistema: {numero(p.pastas)} pastas, {formatar_bytes(p.bytes)}"))
            if not rx.cancelado:
                sistema.salvar(rx, destino)
            return rx

        def pronto(rx) -> None:
            if rx.cancelado:
                self.amb.mensagem("Medição cancelada (nada foi guardado).")
                return
            self.mostrar(rx)
            self.amb.mensagem("Raio-X do sistema pronto. Nada foi movido nem apagado.")

        return self.amb.rodar("Medindo o sistema", trabalho, pronto)
