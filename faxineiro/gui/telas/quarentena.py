"""Quarentena: lotes, espaço, dias; desfazer item ou lote; esvaziar com confirmação dupla."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...formato import formatar_bytes, ha_quanto_tempo, relativo
from ...quarentena import Quarentena
from ..dialogos import confirmar_esvaziar, confirmar_previa, perguntar_conflito, rotulo_flexivel

LOTE = Qt.ItemDataRole.UserRole
ITEM = Qt.ItemDataRole.UserRole + 1


class TelaQuarentena(QWidget):
    def __init__(self, amb) -> None:
        super().__init__()
        self.amb = amb
        layout = QVBoxLayout(self)
        self.resumo = rotulo_flexivel()
        layout.addWidget(self.resumo)
        self.arvore = QTreeWidget()
        self.arvore.setHeaderLabels(["Lote / arquivo", "Tamanho", "Na quarentena"])
        self.arvore.setColumnWidth(0, 520)
        layout.addWidget(self.arvore, 1)

        baixo = QHBoxLayout()
        self.botao_desfazer = QPushButton("Desfazer selecionado")
        self.botao_desfazer.setToolTip("Lote selecionado: traz tudo de volta. Arquivo selecionado: só ele.")
        self.botao_desfazer.clicked.connect(self.desfazer)
        baixo.addWidget(self.botao_desfazer)
        baixo.addStretch(1)
        self.botao_esvaziar = QPushButton("Esvaziar a quarentena…")
        self.botao_esvaziar.clicked.connect(self.esvaziar)
        baixo.addWidget(self.botao_esvaziar)
        layout.addLayout(baixo)
        self.atualizar()

    def ao_mostrar(self) -> None:
        self.atualizar()

    def atualizar(self) -> None:
        leitura, base = self.amb.leitura, self.amb.pasta
        self.arvore.clear()
        itens = leitura.itens_na_quarentena()
        por_lote: dict[int, list] = {}
        for op in itens:
            por_lote.setdefault(op["lote_id"], []).append(op)
        for lote in leitura.lotes_na_quarentena():
            grupo = QTreeWidgetItem(self.arvore, [f"Lote {lote['lote_id']} — {lote['quantidade']} arquivo(s)",
                                                  formatar_bytes(lote["bytes"] or 0), ha_quanto_tempo(lote["desde"])])
            grupo.setData(0, LOTE, lote["lote_id"])
            for op in por_lote.get(lote["lote_id"], []):
                filho = QTreeWidgetItem(grupo, [relativo(op["origem"], base), formatar_bytes(op["tamanho"] or 0),
                                                ha_quanto_tempo(op["concluido_em"])])
                filho.setData(0, ITEM, op["id"])
        total = sum(op["tamanho"] or 0 for op in itens)
        por_unidade: dict[str, int] = {}  # Fase 7B: cada unidade tem a sua quarentena
        for op in itens:
            raiz = Quarentena._raiz_da_quarentena(Path(op["destino"])) or Path(op["destino"]).parent
            por_unidade[str(raiz)] = por_unidade.get(str(raiz), 0) + (op["tamanho"] or 0)
        detalhe = "".join(f"<br>• {onde}: {formatar_bytes(b)}" for onde, b in sorted(por_unidade.items()))
        self.resumo.setText(f"<b>Espaço ocupado pela quarentena: {formatar_bytes(total)}</b> em {len(itens)} arquivo(s). "
                            "Nada aqui foi apagado: dá para desfazer. O espaço de cada unidade só é liberado "
                            f"quando você esvaziar.{detalhe}")
        self.botao_esvaziar.setEnabled(bool(itens))

    def desfazer(self) -> None:
        item = self.arvore.currentItem()
        if item is None:
            self.amb.mensagem("Selecione um lote ou um arquivo.")
            return
        lote, item_id = item.data(0, LOTE), item.data(0, ITEM)
        q = self.amb.quarentena(self.amb.leitura)
        plano = q.planejar_desfazer(item=item_id, lote=lote if item_id is None else None,
                                    conflito=lambda original: perguntar_conflito(original, self))
        if not confirmar_previa(plano, self.amb.pasta, "desfazer", self):
            return

        def trabalho(ctx):
            with self.amb.abrir_indice() as indice:
                return self.amb.quarentena(indice).executar(plano, parar=ctx.parar)

        def pronto(r) -> None:
            self.amb.mensagem(f"{len(r.feitos)} restaurado(s) com hash conferido"
                              + (f", {len(r.falhas)} com problema" if r.falhas else "") + ".")
            if r.falhas:
                QMessageBox.warning(self, "Desfazer", "\n".join(f"{p.origem.name}: {m}" for p, m in r.falhas))
            self.atualizar()

        self.amb.rodar("Desfazendo", trabalho, pronto)

    def esvaziar(self, perguntar_texto=None) -> bool:
        q = self.amb.quarentena(self.amb.leitura)
        plano = q.planejar_esvaziar()
        if not plano.validos:
            self.amb.mensagem("Nada a apagar.")
            return False
        if not confirmar_previa(plano, self.amb.pasta, "ESVAZIAR (apaga de vez)", self):
            return False
        if not confirmar_esvaziar(plano.total_bytes, self, perguntar_texto):
            self.amb.mensagem("Cancelado. Nada foi apagado.")
            return False

        def trabalho(ctx):
            with self.amb.abrir_indice() as indice:
                return self.amb.quarentena(indice).executar(plano, parar=ctx.parar)

        def pronto(r) -> None:
            self.amb.mensagem(f"Liberado: {formatar_bytes(sum(p.tamanho for p in r.feitos))}.")
            self.atualizar()

        return self.amb.rodar("Esvaziando a quarentena", trabalho, pronto)
