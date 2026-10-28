"""Limpezas (Fase 7C.3): temporários e caches da lista fixa, sempre pela quarentena (com desfazer)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import config, limpezas
from ...formato import formatar_bytes, numero
from ..dialogos import confirmar_previa, rotulo_flexivel

COLUNAS = ["Limpeza", "Libera", "Arquivos", "Situação", "O que é"]


class TelaLimpezas(QWidget):
    def __init__(self, amb) -> None:
        super().__init__()
        self.amb = amb
        self.medir = limpezas.medir  # os testes trocam (perfil falso, navegador "aberto")
        self.abertos = limpezas.processos_abertos
        self.achados: list[limpezas.Achado] = []
        layout = QVBoxLayout(self)

        topo = QHBoxLayout()
        self.resumo = rotulo_flexivel("<b>Limpezas seguras</b><br>Clique em <b>Medir</b> para ver quanto cada "
                                      "uma libera (só lê).")
        topo.addWidget(self.resumo, 1)
        self.botao_medir = QPushButton("Medir")
        self.botao_medir.clicked.connect(self.atualizar)
        topo.addWidget(self.botao_medir)
        layout.addLayout(topo)

        self.tabela = QTableWidget(0, len(COLUNAS))
        self.tabela.setHorizontalHeaderLabels(COLUNAS)
        self.tabela.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.tabela.setColumnWidth(0, 260)
        self.tabela.setColumnWidth(3, 260)
        self.tabela.verticalHeader().hide()
        self.tabela.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabela.setWordWrap(True)
        layout.addWidget(self.tabela, 1)

        baixo = QHBoxLayout()
        self.botao_limpar = QPushButton("Mandar as marcadas para a quarentena…")
        self.botao_limpar.clicked.connect(self.limpar)
        self.botao_limpar.setEnabled(False)
        baixo.addStretch(1)
        baixo.addWidget(self.botao_limpar)
        layout.addLayout(baixo)
        nota = QLabel("Tudo vai para a quarentena do C: — dá para desfazer pela tela Quarentena, e o espaço só é "
                      "liberado quando você esvaziar. Navegador aberto fica de fora. Precisa do modo PC real "
                      "(menu Segurança). Lista estudada no BleachBit.")
        nota.setWordWrap(True)
        layout.addWidget(nota)

    def atualizar(self) -> bool:
        def trabalho(ctx):
            return self.medir(parar=ctx.parar)

        def pronto(achados) -> None:
            self.mostrar(achados)
            self.amb.mensagem("Medido. Nada foi movido.")

        return self.amb.rodar("Medindo as limpezas", trabalho, pronto)

    def mostrar(self, achados: list[limpezas.Achado]) -> None:
        self.achados = achados
        self.tabela.setRowCount(len(achados))
        for linha, a in enumerate(achados):
            nome = QTableWidgetItem(a.limpeza.titulo)
            pode = a.motivo is None
            nome.setFlags(nome.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if not pode:
                nome.setFlags(nome.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            nome.setCheckState(Qt.CheckState.Checked if pode else Qt.CheckState.Unchecked)
            situacao = a.motivo or "pode limpar"
            if pode and a.recentes:
                situacao += f" ({numero(a.recentes)} recentes ficam)"
            valores = [nome, QTableWidgetItem(formatar_bytes(a.bytes)), QTableWidgetItem(numero(len(a.arquivos))),
                       QTableWidgetItem(situacao), QTableWidgetItem(a.limpeza.explicacao)]
            for coluna, item in enumerate(valores):
                if coluna in (1, 2):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setToolTip("\n".join(str(p) for p in a.pastas) if coluna == 0 else item.text())
                self.tabela.setItem(linha, coluna, item)
        self.tabela.resizeRowsToContents()
        possivel = sum(a.bytes for a in achados if a.motivo is None)
        self.resumo.setText(f"<b>Limpezas seguras</b>: até {formatar_bytes(possivel)} podem ir para a quarentena.")
        self.botao_limpar.setEnabled(possivel > 0)

    def marcados(self) -> list[limpezas.Achado]:
        return [a for linha, a in enumerate(self.achados)
                if a.motivo is None and self.tabela.item(linha, 0).checkState() == Qt.CheckState.Checked]

    def limpar(self) -> bool:
        if not self.amb.pc_real:
            QMessageBox.information(self, "Limpezas", "As limpezas mexem no PC de verdade: ligue o modo PC real "
                                    "(menu Segurança) e tente de novo.")
            return False
        escolhidos = self.marcados()
        if not escolhidos:
            self.amb.mensagem("Marque pelo menos uma limpeza.")
            return False
        plano = limpezas.planejar(self.amb.quarentena(self.amb.leitura, caches=True), escolhidos, self.abertos)
        if not confirmar_previa(plano, config.PASTA_DO_USUARIO, "limpeza (vai para a quarentena)", self):
            return False

        def trabalho(ctx):
            with self.amb.abrir_indice() as indice:
                return self.amb.quarentena(indice, caches=True).executar(
                    plano, parar=ctx.parar, ao_progredir=lambda f, t: ctx.avisar(f, t, f"Limpando: {f} de {t}"))

        def pronto(r) -> None:
            movido = sum(p.tamanho for p in r.feitos)
            self.amb.mensagem(f"{formatar_bytes(movido)} na quarentena ({len(r.feitos)} arquivos)"
                              + (f"; {len(r.falhas)} em uso ficaram" if r.falhas else "")
                              + ". Esvazie a quarentena do C: para liberar o espaço.")
            self.atualizar()  # mede de novo: mostra o que sobrou (arquivos em uso, recentes)

        return self.amb.rodar("Limpando", trabalho, pronto)
