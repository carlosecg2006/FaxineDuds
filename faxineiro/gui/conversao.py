"""Diálogo "Converter…": escolher o formato, novo ou substituir, ver a prévia e confirmar."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ..conversor import ConversaoRecusada, Ferramentas, formatos_possiveis, planejar_conversao
from ..formato import formatar_duracao, relativo


class DialogoConversao(QDialog):
    def __init__(self, arquivo: Path, base: Path, limite: Path | tuple[Path, ...], ferramentas: Ferramentas,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.arquivo, self.base, self.limite, self.ferramentas = Path(arquivo), base, limite, ferramentas
        self.plano = None
        self.setWindowTitle(f"Converter — {self.arquivo.name}")
        self.resize(560, 300)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.formato = QComboBox()
        for o in formatos_possiveis(self.arquivo, ferramentas):
            self.formato.addItem(o.rotulo + ("" if o.disponivel else f" — {o.motivo}"), o.formato)
            if not o.disponivel:  # aparece, mas não dá para escolher (ex.: sem ffmpeg)
                self.formato.model().item(self.formato.count() - 1).setEnabled(False)
        form.addRow("Converter para:", self.formato)
        self.novo = QRadioButton("Criar um arquivo novo (o original fica)")
        self.substituir = QRadioButton("Substituir (o original vai para a quarentena, dá para desfazer)")
        self.novo.setChecked(True)
        form.addRow("Modo:", self.novo)
        form.addRow("", self.substituir)
        layout.addLayout(form)
        self.previa = QLabel("")
        self.previa.setWordWrap(True)
        self.previa.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.previa, 1)
        self.botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.botoes.button(QDialogButtonBox.StandardButton.Ok).setText("Converter")
        self.botoes.accepted.connect(self.accept)
        self.botoes.rejected.connect(self.reject)
        layout.addWidget(self.botoes)

        self.formato.currentIndexChanged.connect(self.atualizar)
        self.novo.toggled.connect(self.atualizar)
        # começa no primeiro formato disponível
        for i in range(self.formato.count()):
            if self.formato.model().item(i).isEnabled():
                self.formato.setCurrentIndex(i)
                break
        self.atualizar()

    def atualizar(self) -> None:
        """Refaz a prévia a cada mudança (nada acontece no disco até clicar em Converter)."""
        ok = self.botoes.button(QDialogButtonBox.StandardButton.Ok)
        formato = self.formato.currentData()
        if not formato or not self.formato.model().item(self.formato.currentIndex()).isEnabled():
            self.plano = None
            self.previa.setText("Nenhum formato disponível para este arquivo.")
            ok.setEnabled(False)
            return
        try:
            self.plano = planejar_conversao(self.arquivo, formato, modo="novo" if self.novo.isChecked() else "substituir",
                                            limite=self.limite, ferramentas=self.ferramentas)
        except ConversaoRecusada as erro:
            self.plano = None
            self.previa.setText(f"<b>Não dá:</b> {erro}")
            ok.setEnabled(False)
            return
        p = self.plano
        linhas = [f"<b>Prévia</b> (nada foi feito ainda)", f"Novo arquivo: <b>{relativo(p.destino, self.base)}</b>"
                  + (" (nome trocado: já existe um igual)" if p.renomeado else ""), f"Como: {p.como}"]
        if p.duracao:
            linhas.append(f"Duração: {formatar_duracao(p.duracao)}")
        linhas.append("Original: " + ("vai para a <b>quarentena</b> depois de conferir (dá para desfazer)"
                                      if p.modo == "substituir" else "fica intacto"))
        self.previa.setText("<br>".join(linhas))
        ok.setEnabled(True)
