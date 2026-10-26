"""Organizar: sugestão da Fase 4 (regras no 1º nível, IA no assunto), prévia com os protegidos."""

from __future__ import annotations

from collections import defaultdict

from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...formato import formatar_bytes, relativo
from ...ia import ClienteOllama, EnderecoNaoLocal
from ...organizacao import pastas_esvaziadas, planejar_organizacao, sugerir_pastas
from ..dialogos import confirmar_previa, rotulo_flexivel


class TelaOrganizar(QWidget):
    def __init__(self, amb) -> None:
        super().__init__()
        self.amb = amb
        self.plano = None
        layout = QVBoxLayout(self)

        topo = QHBoxLayout()
        self.botao_sugerir = QPushButton("Sugerir organização")
        self.botao_sugerir.clicked.connect(self.sugerir)
        self.refazer = QCheckBox("pedir sugestões novas")
        self.usar_ia = QCheckBox("usar a IA para os assuntos")
        self.usar_ia.setChecked(True)
        topo.addWidget(self.botao_sugerir)
        topo.addWidget(self.refazer)
        topo.addWidget(self.usar_ia)
        topo.addStretch(1)
        layout.addLayout(topo)

        self.aviso = QLabel("A pasta principal vem do tipo do arquivo; a IA só sugere o assunto. "
                            "Projetos, programas, jogos e pastas da nuvem nunca são mexidos.")
        self.aviso.setWordWrap(True)
        layout.addWidget(self.aviso)

        self.arvore = QTreeWidget()
        self.arvore.setHeaderLabels(["Pasta nova / arquivo", "De onde vem", "Tamanho"])
        self.arvore.setColumnWidth(0, 380)
        self.arvore.setColumnWidth(1, 380)
        layout.addWidget(self.arvore, 1)

        baixo = QHBoxLayout()
        self.resumo = rotulo_flexivel()
        baixo.addWidget(self.resumo, 1)
        self.botao_aplicar = QPushButton("Aplicar organização")
        self.botao_aplicar.setEnabled(False)
        self.botao_aplicar.clicked.connect(self.aplicar)
        baixo.addWidget(self.botao_aplicar)
        layout.addLayout(baixo)

    def ao_mostrar(self) -> None:
        pass

    def sugerir(self) -> None:
        pasta, refazer = self.amb.pasta, self.refazer.isChecked()
        try:
            cliente = ClienteOllama() if self.usar_ia.isChecked() else None
        except EnderecoNaoLocal as erro:
            QMessageBox.warning(self, "IA", str(erro))
            cliente = None

        def trabalho(ctx):
            ctx.avisar(0, 0, "Pensando nas pastas")
            with self.amb.abrir_indice() as indice:
                r = sugerir_pastas(indice, pasta, cliente, refazer=refazer, parar=ctx.parar)
                plano = planejar_organizacao(indice, pasta, self.amb.quarentena(indice))
            return r, plano

        self.amb.rodar("Sugerindo organização", trabalho, self._mostrar)

    def _mostrar(self, resultado) -> None:
        r, plano = resultado
        self.plano = plano
        base = self.amb.pasta
        self.arvore.clear()
        por_destino = defaultdict(list)
        for p in plano.validos:
            por_destino[relativo(p.destino.parent, base)].append(p)
        for pasta in sorted(por_destino):
            grupo = QTreeWidgetItem(self.arvore, [pasta + "\\", f"{len(por_destino[pasta])} arquivo(s)", ""])
            for p in por_destino[pasta]:
                nome = p.destino.name + ("  (nome trocado)" if p.renomeado else "")
                QTreeWidgetItem(grupo, [nome, relativo(p.origem, base), formatar_bytes(p.tamanho)])
        if plano.ignorados:
            prot = QTreeWidgetItem(self.arvore, [f"Protegidos — não mexo ({len(plano.ignorados)})", "", ""])
            for arquivo, motivo in plano.ignorados:
                QTreeWidgetItem(prot, [relativo(arquivo, base), motivo, ""])
            prot.setExpanded(True)
        avisos = " ".join(dict.fromkeys(r.avisos))
        origem = (f"sugestões novas: {r.por_ia} pela IA, {r.por_regras} por regras" if r.sugeridos
                  else "sugestões guardadas da última vez")
        self.resumo.setText(f"{len(plano.validos)} arquivo(s) a mover ({origem}). {avisos}")
        self.botao_aplicar.setEnabled(bool(plano.validos))

    def aplicar(self) -> None:
        if self.plano is None or not confirmar_previa(self.plano, self.amb.pasta, "organizar", self):
            return
        plano, base = self.plano, self.amb.pasta

        def trabalho(ctx):
            with self.amb.abrir_indice() as indice:
                q = self.amb.quarentena(indice)
                r = q.executar(plano, parar=ctx.parar, ao_progredir=lambda f, t: ctx.avisar(f, t, f"Movendo {f}/{t}"))
                vazias = pastas_esvaziadas([p.origem for p in r.feitos], base)
                return r, q.planejar_remover_pastas(vazias, "pastas esvaziadas pelo organizar")

        self.amb.rodar("Organizando", trabalho, self._organizado)

    def _organizado(self, resultado) -> None:
        r, plano_pastas = resultado
        self.amb.mensagem(f"Lote {r.lote_id}: {len(r.feitos)} movidos. Para desfazer: tela Quarentena.")
        self.botao_aplicar.setEnabled(False)
        self.plano = None
        if plano_pastas.validos and confirmar_previa(plano_pastas, self.amb.pasta,
                                                    "remover pastas que o organizar esvaziou", self):
            lote = r.lote_id

            def trabalho(ctx):
                with self.amb.abrir_indice() as indice:
                    return self.amb.quarentena(indice).executar(plano_pastas, lote_id=lote)

            self.amb.rodar("Removendo pastas vazias", trabalho,
                           lambda r2: self.amb.mensagem(f"{len(r2.feitos)} pasta(s) vazia(s) removida(s) no lote {lote}."))
        self.arvore.clear()
