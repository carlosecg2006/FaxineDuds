"""Início: Sincronizar (scanner) e visão panorâmica — espaço por tipo e mapa de blocos por pasta."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...formato import formatar_bytes, numero, relativo
from ...raiox import totais_por_categoria
from ...scanner import escanear
from ..mapa import MapaBlocos


class TelaInicio(QWidget):
    def __init__(self, amb) -> None:
        super().__init__()
        self.amb = amb
        self.atual: Path = amb.pasta
        layout = QVBoxLayout(self)

        topo = QHBoxLayout()
        self.titulo = QLabel()
        self.titulo.setWordWrap(True)
        self.botao_sync = QPushButton("Sincronizar")
        self.botao_sync.setToolTip("Varre a pasta e atualiza o índice (só relê o que mudou)")
        self.botao_sync.clicked.connect(self.sincronizar)
        topo.addWidget(self.titulo, 1)
        topo.addWidget(self.botao_sync)
        layout.addLayout(topo)

        meio = QHBoxLayout()
        self.tabela = QTableWidget(0, 3)
        self.tabela.setHorizontalHeaderLabels(["Tipo", "Arquivos", "Espaço"])
        self.tabela.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabela.verticalHeader().hide()
        self.tabela.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabela.setFixedWidth(320)
        meio.addWidget(self.tabela)

        lado = QVBoxLayout()
        navegacao = QHBoxLayout()
        self.botao_voltar = QPushButton("← Voltar")
        self.botao_voltar.clicked.connect(self.voltar)
        self.caminho = QLabel()
        navegacao.addWidget(self.botao_voltar)
        navegacao.addWidget(self.caminho, 1)
        lado.addLayout(navegacao)
        self.mapa = MapaBlocos()
        self.mapa.pastaClicada.connect(self.entrar)
        lado.addWidget(self.mapa, 1)
        meio.addLayout(lado, 1)
        layout.addLayout(meio, 1)
        self.atualizar()

    def ao_mostrar(self) -> None:
        self.atualizar()

    def atualizar(self) -> None:
        indice = self.amb.leitura
        total = indice.contar()
        self.titulo.setText(f"<b>{self.amb.pasta}</b><br>{numero(total)} arquivo(s) no índice"
                            + ("" if indice.foi_escaneada(str(self.amb.pasta)) else
                               " — ainda não sincronizado: clique em Sincronizar."))
        linhas = totais_por_categoria(indice, self.atual)
        self.tabela.setRowCount(len(linhas))
        for i, l in enumerate(linhas):
            for j, valor in enumerate((l["categoria"] or "?", numero(l["quantidade"]), formatar_bytes(l["bytes"] or 0))):
                self.tabela.setItem(i, j, QTableWidgetItem(valor))
        self.mapa.definir_blocos(indice.tamanho_por_pasta(self.atual))
        rel = relativo(self.atual, self.amb.pasta)
        self.caminho.setText("pasta principal" if rel == "." else rel)
        self.botao_voltar.setEnabled(self.atual != self.amb.pasta)

    def entrar(self, nome: str) -> None:
        self.atual = self.atual / nome
        self.atualizar()

    def voltar(self) -> None:
        if self.atual != self.amb.pasta:
            self.atual = self.atual.parent
            self.atualizar()

    def sincronizar(self) -> None:
        pasta = self.amb.pasta

        def trabalho(ctx):
            with self.amb.abrir_indice() as indice:
                return escanear(pasta, indice, parar=ctx.parar,
                                ao_progredir=lambda p: ctx.avisar(p.varridos, 0,
                                                                  f"Sincronizando: {numero(p.varridos)} arquivos"))

        def pronto(p) -> None:
            if p.cancelado:
                self.amb.mensagem(f"Sincronização cancelada em {numero(p.varridos)} arquivos (nada foi removido do índice).")
            else:
                self.amb.mensagem(f"Sincronizado: {p.novos} novos, {p.alterados} alterados, "
                                  f"{p.removidos} sumiram, {p.ignorados} ignorados.")
            self.atualizar()

        self.amb.rodar("Sincronizando", trabalho, pronto)
