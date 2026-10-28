"""Status da IA: modelo, RAM, quanto cada modelo precisa; descrever um arquivo ou os pendentes."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...config import dentro_da_pasta_teste
from ...descricoes import descrever, descrever_arquivo
from ...formato import formatar_duracao
from ...ia import ClienteOllama, EnderecoNaoLocal, avaliar_ia, memoria_necessaria
from ...memoria import MB, memoria_disponivel, memoria_total


class TelaIA(QWidget):
    def __init__(self, amb) -> None:
        super().__init__()
        self.amb = amb
        layout = QVBoxLayout(self)
        self.memoria = QLabel("")
        self.status = QLabel("Clique em Verificar para ver o Ollama.")
        self.status.setWordWrap(True)
        layout.addWidget(self.memoria)
        layout.addWidget(self.status)
        self.modelos = QTableWidget(0, 3)
        self.modelos.setHorizontalHeaderLabels(["Modelo", "Arquivo", "Precisa de RAM livre"])
        self.modelos.horizontalHeader().setStretchLastSection(True)
        self.modelos.verticalHeader().hide()
        self.modelos.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.modelos, 1)

        botoes = QHBoxLayout()
        verificar = QPushButton("Verificar")
        verificar.clicked.connect(self.verificar)
        um = QPushButton("Descrever este arquivo…")
        um.clicked.connect(self.descrever_um)
        pendentes = QPushButton("Descrever pendentes")
        pendentes.setToolTip("Regras descrevem tudo; a IA só o que ficou para revisar (com estimativa de tempo)")
        pendentes.clicked.connect(self.descrever_pendentes)
        for b in (verificar, um, pendentes):
            botoes.addWidget(b)
        botoes.addStretch(1)
        layout.addLayout(botoes)
        self.resultado = QLabel("")
        self.resultado.setWordWrap(True)
        layout.addWidget(self.resultado)

        self._relogio = QTimer(self, interval=5000)  # a RAM livre muda o tempo todo
        self._relogio.timeout.connect(self._mostrar_memoria)
        self._relogio.start()
        self._mostrar_memoria()

    def ao_mostrar(self) -> None:
        self._mostrar_memoria()

    def encerrar(self) -> None:
        self._relogio.stop()

    def _mostrar_memoria(self) -> None:
        livre, total = memoria_disponivel(), memoria_total()
        if livre is not None:
            self.memoria.setText(f"<b>RAM disponível agora: {livre // MB} MB</b> de {(total or 0) // MB} MB")

    def _cliente(self) -> ClienteOllama | None:
        try:
            return ClienteOllama()
        except EnderecoNaoLocal as erro:
            QMessageBox.warning(self, "IA", str(erro))
            return None

    def verificar(self) -> None:
        cliente = self._cliente()

        def trabalho(ctx):
            return avaliar_ia(cliente)

        def pronto(r) -> None:
            st, pode, aviso = r
            if not st.ligado:
                self.status.setText(f"Ollama DESLIGADO ({st.erro}). O app usa só regras.")
                return
            self.status.setText(f"Ollama ligado (versão {st.versao}), só neste PC. Modelo: <b>{cliente.modelo}</b>. "
                                f"Visão: {st.modelo_visao or 'não instalada'}. "
                                + ("<b>Dá para usar a IA agora.</b>" if pode else aviso))
            self.modelos.setRowCount(len(st.modelos))
            for i, nome in enumerate(st.modelos):
                valores = (nome + (" ← em uso" if nome == cliente.modelo else ""),
                           f"{st.tamanhos.get(nome, 0) // MB} MB", f"~{memoria_necessaria(st, nome) // MB} MB")
                for j, v in enumerate(valores):
                    self.modelos.setItem(i, j, QTableWidgetItem(v))

        self.amb.rodar("Verificando a IA", trabalho, pronto)

    def descrever_um(self, caminho: str | None = None) -> None:
        if not caminho:
            caminho, _ = QFileDialog.getOpenFileName(self, "Escolha um arquivo", str(self.amb.pasta))
        if not caminho:
            return
        if not dentro_da_pasta_teste(Path(caminho), self.amb.limite):
            QMessageBox.warning(self, "IA", f"Durante o desenvolvimento só posso usar arquivos de {self.amb.limite}.")
            return
        cliente = self._cliente()

        def trabalho(ctx):
            ctx.avisar(0, 0, f"Descrevendo {Path(caminho).name}")
            with self.amb.abrir_indice() as indice:
                p = descrever_arquivo(indice, caminho, cliente)
                return p, indice.buscar(str(Path(caminho).resolve()))

        def pronto(r) -> None:
            p, linha = r
            avisos = " ".join(dict.fromkeys(p.avisos))
            if linha is None:
                self.resultado.setText(avisos)
                return
            quem = {"ia": "IA", "ia_visao": "IA com visão", "regras": "regras"}[linha["descricao_origem"]]
            self.resultado.setText(f"<b>{linha['nome']}</b>: {linha['descricao']} <i>(por {quem})</i> {avisos}")

        self.amb.rodar("Descrevendo um arquivo", trabalho, pronto)

    def descrever_pendentes(self) -> None:
        cliente, pasta = self._cliente(), self.amb.pasta

        def trabalho(ctx):
            def progresso(p):
                if p.total:
                    ctx.avisar(p.feitos, p.total, f"IA: {p.feitos}/{p.total} — faltam ~{formatar_duracao(p.estimativa_s)}")

            with self.amb.abrir_indice() as indice:
                return descrever(indice, pasta, cliente, parar=ctx.parar, ao_progredir=progresso)

        def pronto(p) -> None:
            avisos = " ".join(dict.fromkeys(p.avisos))
            estado = "pausado (rode de novo para continuar)" if p.pausado else "pronto"
            self.resultado.setText(f"Regras: {p.por_regras} novos. IA: {p.por_ia} descritos de {p.total}; "
                                   f"faltam revisar {p.revisar}. {estado}. {avisos}")

        self.amb.rodar("Descrevendo pendentes", trabalho, pronto)
