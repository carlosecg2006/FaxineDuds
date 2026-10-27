"""Faxina: duplicados, pesados e lixo do Raio-X, com caixas de seleção e "Mandar para quarentena"."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import raiox
from ...config import MB, PESADO_MINIMO, PESADO_MINIMO_TESTE
from ...formato import formatar_bytes, relativo
from ..dialogos import confirmar_previa, rotulo_flexivel
from ..mover import mover_para_outra_unidade

CAMINHO = Qt.ItemDataRole.UserRole
MANTER = Qt.ItemDataRole.UserRole + 1  # no item do grupo: caminho da cópia escolhida para ficar
HASH = Qt.ItemDataRole.UserRole + 2  # no item do grupo: hash BLAKE3 de todas as cópias


def _arvore(colunas: list[str]) -> QTreeWidget:
    a = QTreeWidget()
    a.setHeaderLabels(colunas)
    a.setColumnWidth(0, 460)
    return a


def _item_marcavel(pai, textos: list[str], caminho: str, marcado: bool = False) -> QTreeWidgetItem:
    item = QTreeWidgetItem(pai, textos)
    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
    item.setCheckState(0, Qt.CheckState.Checked if marcado else Qt.CheckState.Unchecked)
    item.setData(0, CAMINHO, caminho)
    return item


class TelaFaxina(QWidget):
    def __init__(self, amb) -> None:
        super().__init__()
        self.amb = amb
        layout = QVBoxLayout(self)

        topo = QHBoxLayout()
        self.botao_analisar = QPushButton("Analisar")
        self.botao_analisar.setToolTip("Roda o Raio-X: acha duplicados (hash BLAKE3), pesados e lixo")
        self.botao_analisar.clicked.connect(self.analisar)
        topo.addWidget(self.botao_analisar)
        topo.addWidget(QLabel("Pesados a partir de"))
        self.minimo = QDoubleSpinBox(suffix=" MB", decimals=1, maximum=1_000_000)
        self.minimo.setValue(PESADO_MINIMO / MB)
        topo.addWidget(self.minimo)
        self.modo_teste = QCheckBox("modo teste (1 MB)")
        self.modo_teste.toggled.connect(
            lambda v: self.minimo.setValue((PESADO_MINIMO_TESTE if v else PESADO_MINIMO) / MB))
        topo.addWidget(self.modo_teste)
        topo.addStretch(1)
        layout.addLayout(topo)
        self.resumo = rotulo_flexivel("Clique em Analisar.")
        layout.addWidget(self.resumo)

        self.abas = QTabWidget()
        self.duplicados = _arvore(["Arquivo", "Tamanho", "Observação"])
        self.pesados = _arvore(["Arquivo", "Tamanho", "Tipo"])
        self.lixo = _arvore(["Arquivo", "Tamanho", "Por quê"])
        self.abas.addTab(self.duplicados, "Duplicados")
        self.abas.addTab(self.pesados, "Pesados")
        self.abas.addTab(self.lixo, "Lixo")
        layout.addWidget(self.abas, 1)

        baixo = QHBoxLayout()
        marcar = QPushButton("Marcar todas as cópias")
        marcar.setToolTip("Nos duplicados, marca todas as cópias menos a que fica")
        marcar.clicked.connect(self.marcar_copias)
        baixo.addWidget(marcar)
        baixo.addStretch(1)
        self.botao_mover = QPushButton("Mover para outra unidade…")
        self.botao_mover.setToolTip("Pesados: copia para outra unidade (ex.: C: → D:), confere o hash "
                                    "e manda o original para a quarentena")
        self.botao_mover.clicked.connect(lambda: self.mover_pesados())
        self.botao_mover.setVisible(False)
        self.abas.currentChanged.connect(lambda i: self.botao_mover.setVisible(self.abas.widget(i) is self.pesados))
        baixo.addWidget(self.botao_mover)
        self.botao_quarentena = QPushButton("Mandar para quarentena")
        self.botao_quarentena.clicked.connect(self.mandar_para_quarentena)
        baixo.addWidget(self.botao_quarentena)
        layout.addLayout(baixo)

    # --- análise (em segundo plano) -------------------------------------------------

    def analisar(self) -> None:
        pasta, minimo = self.amb.pasta, int(self.minimo.value() * MB)

        def trabalho(ctx):
            with self.amb.abrir_indice() as indice:
                dup = raiox.encontrar_duplicados(
                    indice, pasta, parar=ctx.parar,
                    ao_progredir=lambda p: ctx.avisar(p.feitos, p.total, f"Calculando hashes: {p.feitos}/{p.total}"))
                return {"dup": dup, "pesados": raiox.pesados(indice, pasta, 200, minimo),
                        "lixo": raiox.lixo(indice, pasta), "vazias": raiox.pastas_vazias(pasta)}

        self.amb.rodar("Analisando (Raio-X)", trabalho, self._mostrar)

    def _mostrar(self, r: dict) -> None:
        base = self.amb.pasta
        dup = r["dup"]
        self.duplicados.clear()
        self._grupos_radio = []  # guarda os QButtonGroup (senão o Python os apaga)
        for n, g in enumerate(dup.grupos, 1):
            grupo = QTreeWidgetItem(self.duplicados, [f"Grupo {n}: {len(g.arquivos)} cópias — {g.motivo}",
                                                      f"libera {formatar_bytes(g.recuperavel)}", "Qual fica?"])
            grupo.setData(0, HASH, g.hash_completo)
            botoes = QButtonGroup(self.duplicados)  # só uma cópia "fica" por grupo
            self._grupos_radio.append(botoes)
            for a in g.arquivos:
                item = _item_marcavel(grupo, [relativo(a["caminho"], base), formatar_bytes(a["tamanho"]), ""],
                                      a["caminho"])
                sugerida = a["id"] == g.manter["id"]
                radio = QRadioButton("fica (sugerida: a mais antiga)" if sugerida else "fica")
                botoes.addButton(radio)
                self.duplicados.setItemWidget(item, 2, radio)
                radio.toggled.connect(lambda ligado, gr=grupo, it=item: ligado and self.escolher_manter(gr, it))
                if sugerida:
                    radio.setChecked(True)
            grupo.setExpanded(True)
        self.pesados.clear()
        for a in r["pesados"]:
            _item_marcavel(self.pesados, [relativo(a["caminho"], base), formatar_bytes(a["tamanho"]),
                                          f"{a['tipo_real']} ({a['categoria']})"], a["caminho"])
        self.lixo.clear()
        lx = r["lixo"]
        for a in lx.temporarios:
            _item_marcavel(self.lixo, [relativo(a["caminho"], base), formatar_bytes(a["tamanho"]), "temporário"],
                           a["caminho"])
        for a in lx.vazios:
            _item_marcavel(self.lixo, [relativo(a["caminho"], base), "0 B", "arquivo vazio"], a["caminho"])
        for p in r["vazias"]:
            QTreeWidgetItem(self.lixo, [relativo(p, base) + "\\", "", "pasta vazia (só aviso)"])
        cancelado = " (cancelado: rode de novo para terminar)" if dup.cancelado else ""
        self.resumo.setText(f"Dá para liberar {formatar_bytes(dup.recuperavel + lx.recuperavel)}: "
                            f"{len(dup.grupos)} grupos de duplicados, {len(lx.temporarios)} temporários{cancelado}")

    def ao_mostrar(self) -> None:
        pass

    def pasta_mudou(self) -> None:
        for arvore in (self.duplicados, self.pesados, self.lixo):
            arvore.clear()
        self.resumo.setText(f"Pasta: {self.amb.pasta}. Clique em Analisar.")

    def mover_pesados(self, escolher_destino=None) -> bool:
        """Fase 7B: os pesados marcados vão para outra unidade."""
        caminhos = [i.data(0, CAMINHO) for i in self._marcados_em(self.pesados)]
        return mover_para_outra_unidade(self.amb, self, caminhos, escolher_destino=escolher_destino,
                                        ao_terminar=lambda r: self.analisar())

    # --- ação --------------------------------------------------------------------

    def escolher_manter(self, grupo: QTreeWidgetItem, escolhida: QTreeWidgetItem) -> None:
        """A cópia escolhida para ficar nunca pode ser marcada para a quarentena (sempre sobra uma)."""
        grupo.setData(0, MANTER, escolhida.data(0, CAMINHO))
        for j in range(grupo.childCount()):
            item = grupo.child(j)
            if item is escolhida:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                item.setData(0, Qt.ItemDataRole.CheckStateRole, None)  # some a caixinha: esta fica
            else:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                if item.data(0, Qt.ItemDataRole.CheckStateRole) is None:
                    item.setCheckState(0, Qt.CheckState.Unchecked)

    def marcar_copias(self) -> None:
        """Marca todas as cópias de cada grupo, menos a que fica."""
        for i in range(self.duplicados.topLevelItemCount()):
            grupo = self.duplicados.topLevelItem(i)
            for j in range(grupo.childCount()):
                item = grupo.child(j)
                if item.data(0, CAMINHO) != grupo.data(0, MANTER):
                    item.setCheckState(0, Qt.CheckState.Checked)

    def marcados(self) -> list[QTreeWidgetItem]:
        return self._marcados_em(self.abas.currentWidget())

    @staticmethod
    def _marcados_em(arvore: QTreeWidget) -> list[QTreeWidgetItem]:
        itens = []

        def visitar(item: QTreeWidgetItem) -> None:
            if item.data(0, CAMINHO) and item.checkState(0) == Qt.CheckState.Checked:
                itens.append(item)
            for k in range(item.childCount()):
                visitar(item.child(k))

        for i in range(arvore.topLevelItemCount()):
            visitar(arvore.topLevelItem(i))
        return itens

    def montar_plano(self):
        """Prévia com o executor da Fase 3. Nos duplicados, a cópia que fica é conferida na hora de mover."""
        itens = self.marcados()
        extra = {}
        for i in itens:
            grupo = i.parent()  # só os duplicados têm grupo
            if grupo is not None and grupo.data(0, MANTER):
                if i.data(0, CAMINHO) == grupo.data(0, MANTER):
                    continue  # a cópia que fica nunca entra (proteção extra)
                extra[Path(i.data(0, CAMINHO)).resolve()] = (grupo.data(0, MANTER), grupo.data(0, HASH))
        caminhos = [i.data(0, CAMINHO) for i in itens
                    if i.parent() is None or i.data(0, CAMINHO) != i.parent().data(0, MANTER)]
        q = self.amb.quarentena(self.amb.leitura)
        plano = q.planejar_mover(caminhos, "faxina pela interface")
        for passo in plano.passos:
            manter, hash_ = extra.get(passo.origem, (None, None))
            if manter:
                passo.manter, passo.hash_esperado = Path(manter), hash_
        return plano

    def mandar_para_quarentena(self) -> None:
        plano = self.montar_plano()
        if not plano.passos:
            self.amb.mensagem("Marque pelo menos um arquivo.")
            return
        if not confirmar_previa(plano, self.amb.pasta, "mandar para a quarentena", self):
            return

        def trabalho(ctx):
            with self.amb.abrir_indice() as indice:
                return self.amb.quarentena(indice).executar(
                    plano, parar=ctx.parar, ao_progredir=lambda f, t: ctx.avisar(f, t, f"Movendo {f}/{t}"))

        def pronto(r) -> None:
            falhas = f", {len(r.falhas)} com problema" if r.falhas else ""
            self.amb.mensagem(f"Lote {r.lote_id}: {len(r.feitos)} na quarentena{falhas}. Dá para desfazer na tela Quarentena.")
            self.analisar()

        self.amb.rodar("Mandando para a quarentena", trabalho, pronto)
