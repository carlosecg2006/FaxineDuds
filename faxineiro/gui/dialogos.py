"""Diálogos: prévia (dry-run) de qualquer operação e a confirmação dupla do esvaziar."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QInputDialog,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..formato import formatar_bytes, relativo
from ..quarentena import Plano

def rotulo_flexivel(texto: str = "") -> QLabel:
    """Texto que quebra a linha e nunca obriga a janela a ficar mais larga que a tela."""
    rotulo = QLabel(texto)
    rotulo.setWordWrap(True)
    rotulo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    rotulo.setMinimumWidth(120)
    return rotulo


VERBO = {
    "quarentena": "mandar para a quarentena", "restaurar": "trazer de volta", "esvaziar": "APAGAR DE VEZ",
    "organizar": "mover para as pastas sugeridas", "remover_pasta": "remover estas pastas vazias",
    "mover_unidade": "copiar para a outra unidade, conferir o hash e mandar os originais para a quarentena",
}


class DialogoPrevia(QDialog):
    """Mostra cada passo do plano (e o que fica de fora, com o motivo). Nada acontece antes do OK."""

    def __init__(self, plano: Plano, base: Path, titulo: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Prévia — {titulo}")
        self.resize(760, 520)
        layout = QVBoxLayout(self)
        resumo = QLabel(f"<b>{len(plano.validos)}</b> item(ns), <b>{formatar_bytes(plano.total_bytes)}</b> — "
                        f"vou {VERBO.get(plano.tipo, plano.tipo)}. Nada foi feito ainda.")
        resumo.setWordWrap(True)
        layout.addWidget(resumo)
        if plano.avisos:  # Fase 7B: espaço, quarentena, programas que perdem o caminho...
            avisos = QLabel("<br>".join(f"⚠ {a}" for a in plano.avisos))
            avisos.setWordWrap(True)
            avisos.setTextFormat(Qt.TextFormat.RichText)
            avisos.setStyleSheet("background:#fff3cd;color:#5c4400;border:1px solid #e0c060;padding:6px;")
            layout.addWidget(avisos)

        arvore = QTreeWidget()
        arvore.setHeaderLabels(["Item", "Destino / motivo", "Tamanho"])
        arvore.setColumnWidth(0, 330)
        arvore.setColumnWidth(1, 300)
        validos = QTreeWidgetItem(arvore, [f"Vai acontecer ({len(plano.validos)})"])
        pulados = [p for p in plano.passos if p.problema]
        for p in plano.validos:
            destino = relativo(p.destino, base) if p.destino else ""
            if p.remover_pasta:
                destino = "remover a pasta (se ficar vazia; o desfazer recria)"
            if p.quarentenar_copia:
                destino = "a cópia vai para a quarentena da unidade dela"
            if p.renomeado:
                destino += "  (nome trocado: já existe um igual)"
            if p.manter:
                destino = f"fica: {relativo(p.manter, base)}"
            QTreeWidgetItem(validos, [relativo(p.origem, base), destino, formatar_bytes(p.tamanho)])
        validos.setExpanded(True)
        if pulados:
            grupo = QTreeWidgetItem(arvore, [f"Fica de fora ({len(pulados)})"])
            for p in pulados:
                QTreeWidgetItem(grupo, [relativo(p.origem, base), p.problema, ""])
        if plano.ignorados:
            grupo = QTreeWidgetItem(arvore, [f"Protegidos — não mexo ({len(plano.ignorados)})"])
            for arquivo, motivo in plano.ignorados:
                QTreeWidgetItem(grupo, [relativo(arquivo, base), motivo, ""])
        layout.addWidget(arvore)

        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botoes.button(QDialogButtonBox.StandardButton.Ok).setText("Confirmar")
        botoes.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(plano.validos))
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)


def confirmar_previa(plano: Plano, base: Path, titulo: str, parent: QWidget | None = None) -> bool:
    if not plano.validos and not plano.passos and not plano.ignorados:
        QMessageBox.information(parent, titulo, "Nada a fazer.")
        return False
    return DialogoPrevia(plano, base, titulo, parent).exec() == QDialog.DialogCode.Accepted


def confirmar_esvaziar(espaco: int, parent: QWidget | None = None, perguntar_texto=None,
                       unidade: str | None = None) -> bool:
    """Confirmação dupla (regra 1): sim/não e depois digitar ESVAZIAR."""
    onde = f"a quarentena do {unidade}" if unidade else "TODAS as quarentenas"
    resp = QMessageBox.warning(
        parent, "Esvaziar a quarentena",
        f"Isto vai liberar {formatar_bytes(espaco)} e APAGAR DE VEZ os arquivos de {onde}.\n"
        "NÃO DÁ PARA DESFAZER.\n\nTem certeza?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
    )
    if resp != QMessageBox.StandardButton.Yes:
        return False
    perguntar_texto = perguntar_texto or (
        lambda: QInputDialog.getText(parent, "Confirmação final", "Digite ESVAZIAR para confirmar:"))
    texto, ok = perguntar_texto()
    return bool(ok) and texto == "ESVAZIAR"


def perguntar_conflito(original: Path, parent: QWidget | None = None) -> str:
    caixa = QMessageBox(parent)
    caixa.setWindowTitle("Já existe um arquivo com esse nome")
    caixa.setText(f"Já existe <b>{original.name}</b> no lugar original.<br>Nunca sobrescrevo. O que fazer?")
    renomear = caixa.addButton("Renomear o restaurado", QMessageBox.ButtonRole.AcceptRole)
    caixa.addButton("Pular este", QMessageBox.ButtonRole.RejectRole)
    caixa.setTextFormat(Qt.TextFormat.RichText)
    caixa.exec()
    return "renomear" if caixa.clickedButton() is renomear else "pular"
