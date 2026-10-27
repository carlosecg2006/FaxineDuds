"""Explorador: pastas do índice, lista paginada, busca por nome e descrição, detalhes com miniatura."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...conversor import converter as converter_arquivo
from ...conversor import formatos_possiveis, localizar_ffmpeg
from ...descricoes import descrever_arquivo
from ..conversao import DialogoConversao
from ...formato import formatar_bytes
from ...ia import ClienteOllama, EnderecoNaoLocal
from ..dialogos import confirmar_previa
from ..modelos import ModeloArquivos
from ..sistema import abrir_arquivo, mostrar_na_pasta

PAPEL_CAMINHO = Qt.ItemDataRole.UserRole


class TelaExplorador(QWidget):
    def __init__(self, amb) -> None:
        super().__init__()
        self.amb = amb
        self.pasta_atual: Path = amb.pasta
        layout = QHBoxLayout(self)
        divisor = QSplitter()

        self.arvore = QTreeWidget()
        self.arvore.setHeaderLabels(["Pasta", "Tamanho"])
        self.arvore.setColumnWidth(0, 200)
        self.arvore.itemExpanded.connect(self._expandir)
        self.arvore.currentItemChanged.connect(self._pasta_escolhida)
        divisor.addWidget(self.arvore)

        centro = QWidget()
        cl = QVBoxLayout(centro)
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Buscar por nome ou descrição (em todas as subpastas)...")
        self._espera = QTimer(self, singleShot=True, interval=350)  # busca só quando parar de digitar
        self._espera.timeout.connect(self._buscar)
        self.busca.textChanged.connect(lambda _: self._espera.start())
        cl.addWidget(self.busca)
        self.modelo = ModeloArquivos()
        self.tabela = QTableView()
        self.tabela.setModel(self.modelo)
        self.tabela.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.tabela.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.tabela.verticalHeader().hide()
        self.tabela.horizontalHeader().setStretchLastSection(True)
        self.tabela.setColumnWidth(0, 220)
        self.tabela.selectionModel().currentRowChanged.connect(self._arquivo_escolhido)
        self.tabela.doubleClicked.connect(lambda _: self.abrir())
        self.tabela.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabela.customContextMenuRequested.connect(self._menu)
        cl.addWidget(self.tabela)
        divisor.addWidget(centro)

        detalhes = QWidget()
        dl = QVBoxLayout(detalhes)
        self.miniatura = QLabel("")
        self.miniatura.setFixedSize(110, 110)
        self.miniatura.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dl.addWidget(self.miniatura)
        self.form = QFormLayout()
        self.campos = {}
        for nome in ("Nome", "Pasta", "Tipo real", "Tamanho", "Criado", "Modificado", "Hash", "Descrição", "Origem"):
            rotulo = QLabel("")
            rotulo.setWordWrap(True)
            rotulo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.campos[nome] = rotulo
            self.form.addRow(nome + ":", rotulo)
        dl.addLayout(self.form)
        self.botao_mostrar = QPushButton("Mostrar no Explorador do Windows")
        self.botao_mostrar.setEnabled(False)
        self.botao_mostrar.clicked.connect(self.mostrar_na_pasta)
        dl.addWidget(self.botao_mostrar)
        dl.addStretch(1)
        divisor.addWidget(detalhes)
        divisor.setSizes([230, 600, 300])
        layout.addWidget(divisor)

        self.amb.miniaturas.pronta.connect(self._miniatura_chegou)
        self._caminho_mostrado = ""
        self.recarregar_arvore()

    def ao_mostrar(self) -> None:
        self.recarregar_arvore()

    # --- árvore (filhas carregadas só ao expandir) ---------------------------------

    def _item(self, pai, pasta: Path, nome: str, bytes_: int) -> QTreeWidgetItem:
        item = QTreeWidgetItem(pai, [nome, formatar_bytes(bytes_ or 0)])
        item.setData(0, PAPEL_CAMINHO, str(pasta))
        QTreeWidgetItem(item, ["…"])  # marcador: "tem filhas, carregue quando abrir"
        return item

    def recarregar_arvore(self) -> None:
        self.arvore.clear()
        raiz = self._item(self.arvore, self.amb.pasta, self.amb.pasta.name, 0)
        raiz.setExpanded(True)
        self.arvore.setCurrentItem(raiz)

    def _expandir(self, item: QTreeWidgetItem) -> None:
        if item.childCount() == 1 and item.child(0).data(0, PAPEL_CAMINHO) is None:
            item.takeChild(0)
            pasta = Path(item.data(0, PAPEL_CAMINHO))
            for sub in self.amb.leitura.subpastas(pasta):
                self._item(item, pasta / sub["nome"], sub["nome"], sub["bytes"])

    def _pasta_escolhida(self, item: QTreeWidgetItem | None, _anterior=None) -> None:
        if item is None or item.data(0, PAPEL_CAMINHO) is None:
            return
        self.pasta_atual = Path(item.data(0, PAPEL_CAMINHO))
        if not self.busca.text().strip():
            leitura = self.amb.leitura
            pasta = self.pasta_atual
            self.modelo.trocar_fonte(lambda lim, off: leitura.arquivos_da_pasta(pasta, lim, off))

    def _buscar(self) -> None:
        termo = self.busca.text().strip()
        if not termo:
            self._pasta_escolhida(self.arvore.currentItem())
            return
        leitura, base = self.amb.leitura, self.amb.pasta
        self.modelo.trocar_fonte(lambda lim, off: leitura.buscar_texto(base, termo, lim, off))

    # --- detalhes ------------------------------------------------------------------

    def _arquivo_escolhido(self, atual, _anterior=None) -> None:
        if not atual.isValid():
            return
        l = self.modelo.linha(atual.row())
        p = Path(l["caminho"])
        valores = {
            "Nome": l["nome"], "Pasta": str(p.parent), "Tipo real": f"{l['tipo_real']} ({l['categoria']})"
            + ("" if l["extensao_confere"] else " — extensão não confere!"),
            "Tamanho": formatar_bytes(l["tamanho"]), "Criado": (l["criado_em"] or "").replace("T", " "),
            "Modificado": (l["modificado_em"] or "").replace("T", " "),
            "Hash": (l["hash_completo"][:16] + "…") if l["hash_completo"] else "(ainda não calculado)",
            "Descrição": l["descricao"] or "(sem descrição)",
            "Origem": {"ia": "IA", "ia_visao": "IA (visão)", "regras": "regras"}.get(l["descricao_origem"], "—")
            + (" — marcado para revisar" if l["revisar"] else "")
            + (" — SÓ NA NUVEM (não está baixado neste PC)" if l["aparelho"] == "nuvem" else ""),
        }
        for nome, valor in valores.items():
            self.campos[nome].setText(str(valor))
        self.miniatura.clear()
        self._caminho_mostrado = l["caminho"]
        self.botao_mostrar.setEnabled(True)
        if l["categoria"] == "imagem" and l["aparelho"] != "nuvem":  # só na nuvem: abrir baixaria a foto
            self.amb.miniaturas.pedir(l["caminho"])

    def _miniatura_chegou(self, caminho: str, pix: QPixmap) -> None:
        if caminho == self._caminho_mostrado:
            self.miniatura.setPixmap(pix)

    # --- ações sobre o arquivo selecionado ------------------------------------------

    def selecionado(self):
        indice = self.tabela.currentIndex()
        return self.modelo.linha(indice.row()) if indice.isValid() else None

    def abrir(self) -> None:
        """Clique duplo: abre no programa padrão. Programas pedem confirmação (abrir = executar)."""
        l = self.selecionado()
        if l is None:
            return
        if l["categoria"] == "executavel" and QMessageBox.question(
                self, "Abrir programa", f"{l['nome']} é um programa: abrir vai EXECUTÁ-LO.\nContinuar?",
        ) != QMessageBox.StandardButton.Yes:
            return
        if not abrir_arquivo(l["caminho"]):
            self.amb.mensagem(f"O Windows não tem programa para abrir {l['nome']}.")

    def mostrar_na_pasta(self) -> None:
        l = self.selecionado()
        if l is not None:
            mostrar_na_pasta(l["caminho"])

    def descrever_com_ia(self) -> None:
        l = self.selecionado()
        if l is None:
            return
        caminho = l["caminho"]
        try:
            cliente = ClienteOllama()
        except EnderecoNaoLocal as erro:
            QMessageBox.warning(self, "IA", str(erro))
            return

        def trabalho(ctx):
            ctx.avisar(0, 0, f"Descrevendo {Path(caminho).name}")
            with self.amb.abrir_indice() as indice:
                return descrever_arquivo(indice, caminho, cliente)

        def pronto(p) -> None:
            avisos = " ".join(dict.fromkeys(p.avisos))
            self.amb.mensagem(f"Descrição atualizada{' (por regras)' if p.por_regras else ''}. {avisos}")
            self._recarregar_lista(caminho)

        self.amb.rodar("Descrevendo com IA", trabalho, pronto)

    def mandar_para_quarentena(self) -> None:
        l = self.selecionado()
        if l is None:
            return
        plano = self.amb.quarentena(self.amb.leitura).planejar_mover([l["caminho"]], "explorador")
        if not confirmar_previa(plano, self.amb.pasta, "mandar para a quarentena", self):
            return

        def trabalho(ctx):
            with self.amb.abrir_indice() as indice:
                return self.amb.quarentena(indice).executar(plano, parar=ctx.parar)

        def pronto(r) -> None:
            if r.falhas:
                QMessageBox.warning(self, "Quarentena", r.falhas[0][1])
            else:
                self.amb.mensagem(f"{l['nome']} foi para a quarentena (lote {r.lote_id}); dá para desfazer.")
            self._recarregar_lista()

        self.amb.rodar("Mandando para a quarentena", trabalho, pronto)

    def _recarregar_lista(self, selecionar: str | None = None) -> None:
        if self.busca.text().strip():
            self._buscar()
        else:
            self._pasta_escolhida(self.arvore.currentItem())
        if selecionar:
            for i in range(self.modelo.rowCount()):
                if self.modelo.linha(i)["caminho"] == selecionar:
                    self.tabela.selectRow(i)
                    break

    def converter(self, escolher=None) -> None:
        """Abre o diálogo de conversão; converte em segundo plano (progresso + Cancelar)."""
        l = self.selecionado()
        if l is None:
            return
        ferramentas = localizar_ffmpeg()
        if not formatos_possiveis(l["caminho"], ferramentas):
            self.amb.mensagem("Por enquanto só converto imagens, áudio e vídeo.")
            return
        dialogo = DialogoConversao(Path(l["caminho"]), self.amb.pasta, self.amb.limite, ferramentas, self)
        aceitou = escolher(dialogo) if escolher else dialogo.exec() == DialogoConversao.DialogCode.Accepted
        if not aceitou or dialogo.plano is None:
            return
        plano = dialogo.plano

        def trabalho(ctx):
            with self.amb.abrir_indice() as indice:
                return converter_arquivo(
                    plano, indice=indice, quarentena=self.amb.quarentena(indice), parar=ctx.parar,
                    ferramentas=ferramentas,
                    ao_progredir=lambda f: ctx.avisar(int(f * 100), 100, f"Convertendo {plano.origem.name}: {f:.0%}"))

        def pronto(r) -> None:
            if r.cancelado:
                self.amb.mensagem("Conversão cancelada: nada foi criado, o original está intacto.")
                return
            extra = f" Original na quarentena (lote {r.lote_id})." if r.lote_id else ""
            self.amb.mensagem(f"Convertido em {r.segundos:.1f} s: {r.destino.name}.{extra} {r.aviso}")
            self._recarregar_lista(str(r.destino))

        self.amb.rodar("Convertendo", trabalho, pronto)

    def acoes_do_menu(self) -> list[tuple[str, object]]:
        return [("Abrir", self.abrir), ("Mostrar na pasta", self.mostrar_na_pasta),
                ("Descrever com IA", self.descrever_com_ia), ("Converter…", self.converter),
                ("Mandar para quarentena…", self.mandar_para_quarentena)]

    def _menu(self, posicao) -> None:
        if not self.tabela.indexAt(posicao).isValid():
            return
        self.tabela.selectRow(self.tabela.indexAt(posicao).row())
        menu = QMenu(self)
        for texto, funcao in self.acoes_do_menu():
            menu.addAction(texto, funcao)
        menu.exec(self.tabela.viewport().mapToGlobal(posicao))
