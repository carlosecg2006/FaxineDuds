"""Interface sem abrir janela (QT_QPA_PLATFORM=offscreen, ver conftest)."""

import os
import random
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from faxineiro.gui import dialogos  # noqa: E402
from faxineiro.gui.app import Ambiente, Janela  # noqa: E402
from faxineiro.gui.miniaturas import CarregadorMiniaturas, gerar_miniatura  # noqa: E402
from faxineiro.gui.modelos import TAMANHO_PAGINA, ModeloArquivos  # noqa: E402
from faxineiro.gui.tarefas import GerenteTarefas  # noqa: E402
from faxineiro.indice import Indice  # noqa: E402
from faxineiro.scanner import escanear  # noqa: E402


def _bytes(semente, n=4000):
    return random.Random(semente).randbytes(n)


@pytest.fixture
def area(tmp_path):
    raiz = tmp_path / "pasta_teste"
    (raiz / "Fotos").mkdir(parents=True)
    (raiz / "Downloads").mkdir()
    imagem = QImage(400, 300, QImage.Format.Format_RGB32)
    imagem.fill(QColor("#3388cc"))
    imagem.save(str(raiz / "Fotos" / "praia.png"))
    (raiz / "Fotos" / "praia - Cópia.png").write_bytes((raiz / "Fotos" / "praia.png").read_bytes())
    (raiz / "Downloads" / "video.bin").write_bytes(_bytes(1))
    (raiz / "Downloads" / "video (1).bin").write_bytes(_bytes(1))
    (raiz / "Downloads" / "cache.tmp").write_text("temporario", encoding="utf-8")
    (raiz / "Downloads" / "notas da aula.txt").write_text("redes de computadores", encoding="utf-8")
    return raiz


@pytest.fixture
def amb(tmp_path, area, qtbot):
    banco = tmp_path / "dados" / "indice.sqlite"
    with Indice(banco) as i:
        escanear(area, i)
    a = Ambiente(caminho_indice=banco, pasta=area.resolve(), limite=area.resolve(), gerente=GerenteTarefas(),
                 leitura=Indice(banco), miniaturas=CarregadorMiniaturas(tmp_path / "mini"),
                 local_quarentena=lambda arq: area.resolve() / "_quarentena")
    yield a
    a.gerente.esperar()
    a.leitura.fechar()


@pytest.fixture
def janela(amb, qtbot):
    j = Janela(amb)
    qtbot.addWidget(j)
    yield j
    j.close()  # antes do `amb` fechar o índice: para os temporizadores (busca do Explorador, RAM da IA)


def _esperar_tarefa(qtbot, amb):
    qtbot.waitUntil(lambda: not amb.gerente.ocupado, timeout=20000)


# --- modelo paginado ---------------------------------------------------------------------


def test_modelo_carrega_aos_poucos(qtbot):
    pedidos = []

    def fonte(limite, offset):
        pedidos.append((limite, offset))
        return [{"nome": f"a{i}", "tamanho": i, "tipo_real": "texto", "categoria": "texto",
                 "modificado_em": "2026-10-26T10:00:00", "descricao": "", "caminho": f"C:/a{i}"}
                for i in range(offset, min(offset + limite, 450))]

    m = ModeloArquivos()
    m.trocar_fonte(fonte)
    assert m.rowCount() == TAMANHO_PAGINA and pedidos == [(200, 0)]  # só a 1ª página
    while m.canFetchMore(m.index(0, 0).parent()):
        m.fetchMore(m.index(0, 0).parent())
    assert m.rowCount() == 450 and len(pedidos) == 3
    assert m.data(m.index(5, 1)) == "5 B"


# --- tarefas em segundo plano --------------------------------------------------------------


def test_tarefa_roda_em_thread_com_progresso(qtbot):
    g = GerenteTarefas()
    progresso, resultados = [], []
    g.progresso.connect(lambda f, t, txt: progresso.append(f))

    def trabalho(ctx):
        for i in range(5):
            ctx.avisar(i + 1, 5, "")
        return "ok"

    def terminou(r):
        resultados.append((r, g.ocupado))
        # dá para começar outra tarefa logo depois (o fim só é avisado com a thread já parada)
        resultados.append(g.iniciar("segunda", lambda ctx: "ok2", lambda r2: resultados.append(r2)) is not None)

    g.iniciar("primeira", trabalho, terminou)
    qtbot.waitUntil(lambda: "ok2" in resultados, timeout=5000)
    assert resultados[0] == ("ok", False) and resultados[1] is True
    assert progresso[-1] == 5


def test_tarefa_cancela(qtbot):
    g = GerenteTarefas()
    fim = []

    def trabalho(ctx):
        while not ctx.parar():
            time.sleep(0.01)
        return "cancelado"

    g.iniciar("longa", trabalho, fim.append)
    assert g.iniciar("outra", lambda ctx: None) is None  # uma de cada vez
    g.cancelar()
    qtbot.waitUntil(lambda: fim == ["cancelado"], timeout=5000)


def test_erro_na_tarefa_vira_mensagem(qtbot):
    g = GerenteTarefas()
    erros = []
    g.iniciar("quebra", lambda ctx: 1 / 0, ao_falhar=erros.append)
    qtbot.waitUntil(lambda: bool(erros), timeout=5000)
    assert "division by zero" in erros[0]


# --- janela e telas ------------------------------------------------------------------------


def test_todas_as_telas_abrem(janela, qtbot):
    for i in range(janela.lateral.count()):
        janela.lateral.setCurrentRow(i)
        qtbot.wait(10)
    assert janela.lateral.count() == 9


def test_inicio_mostra_mapa_e_sincroniza(janela, amb, qtbot, area):
    inicio = janela.telas[0]
    assert {b["nome"] for b in inicio.mapa._blocos} == {"Fotos", "Downloads"}
    (area / "Downloads" / "novo.txt").write_text("novo", encoding="utf-8")
    inicio.sincronizar()
    _esperar_tarefa(qtbot, amb)
    assert amb.leitura.buscar(str(area.resolve() / "Downloads" / "novo.txt")) is not None
    inicio.entrar("Downloads")
    assert inicio.botao_voltar.isEnabled()


def test_explorador_busca_por_nome(janela, qtbot):
    exp = janela.telas[1]
    exp.busca.setText("aula")
    exp._buscar()
    assert exp.modelo.rowCount() == 1 and exp.modelo.linha(0)["nome"] == "notas da aula.txt"


def test_faxina_nunca_inclui_a_copia_que_fica(janela, amb, qtbot, monkeypatch, area):
    faxina = janela.telas[2]
    faxina.analisar()
    _esperar_tarefa(qtbot, amb)
    assert faxina.duplicados.topLevelItemCount() == 2
    faxina.marcar_copias()
    plano = faxina.montar_plano()
    assert len(plano.validos) == 2
    mantidas = {p.manter.name for p in plano.validos}
    origens = {p.origem.name for p in plano.validos}
    assert not (mantidas & origens)  # a cópia que fica nunca vai para a quarentena
    monkeypatch.setattr("faxineiro.gui.telas.faxina.confirmar_previa", lambda *a, **k: True)
    faxina.mandar_para_quarentena()
    qtbot.waitUntil(lambda: len(amb.leitura.itens_na_quarentena()) == 2, timeout=20000)
    _esperar_tarefa(qtbot, amb)
    for nome in mantidas:
        assert any(p.name == nome for p in area.rglob(nome) if "_quarentena" not in p.parts)


def _grupo_de_fotos(faxina):
    for i in range(faxina.duplicados.topLevelItemCount()):
        g = faxina.duplicados.topLevelItem(i)
        if g.child(0).data(0, Qt.ItemDataRole.UserRole).endswith(".png"):
            return g
    raise AssertionError("grupo das fotos não apareceu")


def test_faxina_eu_escolho_qual_copia_fica(janela, amb, qtbot):
    faxina = janela.telas[2]
    faxina.analisar()
    _esperar_tarefa(qtbot, amb)
    grupo = _grupo_de_fotos(faxina)
    sugerida = grupo.data(0, Qt.ItemDataRole.UserRole + 1)
    outra = next(grupo.child(j) for j in range(grupo.childCount())
                 if grupo.child(j).data(0, Qt.ItemDataRole.UserRole) != sugerida)
    faxina.duplicados.itemWidget(outra, 2).setChecked(True)  # troco: agora fica a outra
    nova = outra.data(0, Qt.ItemDataRole.UserRole)
    assert grupo.data(0, Qt.ItemDataRole.UserRole + 1) == nova
    assert not (outra.flags() & Qt.ItemFlag.ItemIsUserCheckable)  # a que fica não dá para marcar
    faxina.marcar_copias()
    plano = faxina.montar_plano()
    origens = {str(p.origem) for p in plano.validos}
    assert str(Path(sugerida).resolve()) in origens  # a antiga sugerida agora vai para a quarentena
    assert str(Path(nova).resolve()) not in origens
    passo = next(p for p in plano.validos if p.origem == Path(sugerida).resolve())
    assert passo.manter == Path(nova) and passo.hash_esperado  # conferida por hash na hora de mover


def test_faxina_a_que_fica_nunca_entra_mesmo_forcando(janela, amb, qtbot):
    faxina = janela.telas[2]
    faxina.analisar()
    _esperar_tarefa(qtbot, amb)
    for i in range(faxina.duplicados.topLevelItemCount()):
        g = faxina.duplicados.topLevelItem(i)
        for j in range(g.childCount()):
            g.child(j).setCheckState(0, Qt.CheckState.Checked)  # força TODAS marcadas (até a que fica)
    plano = faxina.montar_plano()
    assert len(plano.validos) == 2  # 2 grupos de 2 cópias: sempre sobra uma em cada


def test_faxina_move_com_a_copia_escolhida(janela, amb, qtbot, monkeypatch, area):
    faxina = janela.telas[2]
    faxina.analisar()
    _esperar_tarefa(qtbot, amb)
    grupo = _grupo_de_fotos(faxina)
    sugerida = grupo.data(0, Qt.ItemDataRole.UserRole + 1)
    outra = next(grupo.child(j) for j in range(grupo.childCount())
                 if grupo.child(j).data(0, Qt.ItemDataRole.UserRole) != sugerida)
    faxina.duplicados.itemWidget(outra, 2).setChecked(True)
    escolhida = outra.data(0, Qt.ItemDataRole.UserRole)
    faxina.marcar_copias()
    monkeypatch.setattr("faxineiro.gui.telas.faxina.confirmar_previa", lambda *a, **k: True)
    faxina.mandar_para_quarentena()
    qtbot.waitUntil(lambda: len(amb.leitura.itens_na_quarentena()) == 2, timeout=20000)
    _esperar_tarefa(qtbot, amb)
    assert not Path(sugerida).exists()  # a sugerida foi para a quarentena
    assert Path(escolhida).exists()  # a que EU escolhi ficou no lugar


def _explorador_em(janela, nome_pasta):
    exp = janela.telas[1]
    raiz = exp.arvore.topLevelItem(0)
    for i in range(raiz.childCount()):
        if raiz.child(i).text(0) == nome_pasta:
            exp.arvore.setCurrentItem(raiz.child(i))
    return exp


def test_explorador_abre_e_mostra_na_pasta(janela, monkeypatch):
    abertos, mostrados = [], []
    monkeypatch.setattr("faxineiro.gui.telas.explorador.abrir_arquivo", lambda c: abertos.append(c) or True)
    monkeypatch.setattr("faxineiro.gui.telas.explorador.mostrar_na_pasta", lambda c: mostrados.append(c))
    exp = _explorador_em(janela, "Fotos")
    exp.tabela.selectRow(0)
    assert exp.botao_mostrar.isEnabled()
    exp.tabela.doubleClicked.emit(exp.tabela.currentIndex())  # clique duplo
    exp.botao_mostrar.click()
    assert abertos and abertos[0].endswith(".png")
    assert mostrados == abertos


def test_explorador_pede_confirmacao_para_abrir_programa(janela, monkeypatch, area, amb):
    (area / "Downloads" / "instalar.exe").write_bytes(b"MZ" + bytes(300))
    with Indice(amb.caminho_indice) as i:
        escanear(area, i)
    abertos = []
    monkeypatch.setattr("faxineiro.gui.telas.explorador.abrir_arquivo", lambda c: abertos.append(c) or True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    exp = _explorador_em(janela, "Downloads")
    linha = next(i for i in range(exp.modelo.rowCount()) if exp.modelo.linha(i)["nome"] == "instalar.exe")
    exp.tabela.selectRow(linha)
    exp.abrir()
    assert abertos == []  # disse "não": não executou


def test_explorador_menu_do_botao_direito(janela):
    nomes = [t for t, _ in janela.telas[1].acoes_do_menu()]
    assert nomes == ["Abrir", "Mostrar na pasta", "Descrever com IA", "Converter…", "Mandar para quarentena…",
                     "Mover para outra unidade…"]


def test_explorador_manda_para_quarentena(janela, amb, qtbot, monkeypatch, area):
    monkeypatch.setattr("faxineiro.gui.telas.explorador.confirmar_previa", lambda *a, **k: True)
    exp = _explorador_em(janela, "Downloads")
    linha = next(i for i in range(exp.modelo.rowCount()) if exp.modelo.linha(i)["nome"] == "cache.tmp")
    exp.tabela.selectRow(linha)
    exp.mandar_para_quarentena()
    _esperar_tarefa(qtbot, amb)
    assert not (area / "Downloads" / "cache.tmp").exists()
    assert len(amb.leitura.itens_na_quarentena()) == 1


def test_explorador_descreve_com_ia(janela, amb, qtbot, monkeypatch, area):
    from .falsos import ClienteFalso

    monkeypatch.setattr("faxineiro.gui.telas.explorador.ClienteOllama", lambda: ClienteFalso())
    exp = _explorador_em(janela, "Downloads")
    linha = next(i for i in range(exp.modelo.rowCount()) if exp.modelo.linha(i)["nome"] == "notas da aula.txt")
    exp.tabela.selectRow(linha)
    exp.descrever_com_ia()
    _esperar_tarefa(qtbot, amb)
    atual = amb.leitura.buscar(str(area.resolve() / "Downloads" / "notas da aula.txt"))
    assert atual["descricao_origem"] == "ia"


def test_dialogo_conversao_previa_e_sem_ffmpeg(area, qtbot):
    from faxineiro.conversor import Ferramentas
    from faxineiro.gui.conversao import DialogoConversao

    d = DialogoConversao(area / "Fotos" / "praia.png", area, area, Ferramentas(None, None))
    qtbot.addWidget(d)
    formatos = [d.formato.itemData(i) for i in range(d.formato.count())]
    assert "png" not in formatos and "jpg" in formatos
    assert d.plano is not None and "Prévia" in d.previa.text() and "fica intacto" in d.previa.text()
    d.substituir.setChecked(True)
    assert d.plano.modo == "substituir" and "quarentena" in d.previa.text()

    (area / "Downloads" / "filme.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + bytes(64))
    d2 = DialogoConversao(area / "Downloads" / "filme.mp4", area, area, Ferramentas(None, None))
    qtbot.addWidget(d2)
    assert d2.plano is None and not d2.botoes.button(d2.botoes.StandardButton.Ok).isEnabled()
    assert "ffmpeg" in d2.formato.itemText(0)


def test_explorador_converte_imagem(janela, amb, qtbot, area):
    exp = _explorador_em(janela, "Fotos")
    linha = next(i for i in range(exp.modelo.rowCount()) if exp.modelo.linha(i)["nome"] == "praia.png")
    exp.tabela.selectRow(linha)

    def escolher(dialogo):
        i = next(i for i in range(dialogo.formato.count()) if dialogo.formato.itemData(i) == "jpg")
        dialogo.formato.setCurrentIndex(i)
        return True

    exp.converter(escolher=escolher)
    _esperar_tarefa(qtbot, amb)
    novo = area.resolve() / "Fotos" / "praia.jpg"
    assert novo.exists() and (area / "Fotos" / "praia.png").exists()
    assert amb.leitura.buscar(str(novo)) is not None  # entrou no índice


def test_quarentena_esvazia_so_com_a_segunda_confirmacao(janela, amb, qtbot, monkeypatch, area):
    q = amb.quarentena(amb.leitura)
    q.executar(q.planejar_mover([area / "Downloads" / "cache.tmp"]))
    tela = janela.telas[4]
    tela.atualizar()
    assert "10 B" in tela.resumo.text()
    monkeypatch.setattr("faxineiro.gui.telas.quarentena.confirmar_previa", lambda *a, **k: True)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Yes)
    assert tela.esvaziar(perguntar_texto=lambda: ("esvaziar", True)) is False  # minúsculo: não vale
    assert len(amb.leitura.itens_na_quarentena()) == 1
    assert tela.esvaziar(perguntar_texto=lambda: ("ESVAZIAR", True)) is True
    _esperar_tarefa(qtbot, amb)
    assert amb.leitura.itens_na_quarentena() == []


def test_confirmar_esvaziar_recusa_no_primeiro_nao(monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.No)
    chamado = []
    assert dialogos.confirmar_esvaziar(100, perguntar_texto=lambda: chamado.append(1) or ("ESVAZIAR", True)) is False
    assert chamado == []  # nem pergunta a 2ª vez


def test_previa_mostra_protegidos(qtbot, amb, area):
    from faxineiro.quarentena import Plano

    plano = Plano("organizar", "teste", ignorados=[(area / "OneDrive" / "x.txt", "pasta da nuvem")])
    from PySide6.QtWidgets import QDialogButtonBox, QTreeWidget

    d = dialogos.DialogoPrevia(plano, area, "organizar")
    qtbot.addWidget(d)
    arvore = d.findChild(QTreeWidget)
    grupos = [arvore.topLevelItem(i).text(0) for i in range(arvore.topLevelItemCount())]
    assert any(g.startswith("Protegidos") for g in grupos)
    protegido = next(arvore.topLevelItem(i) for i in range(arvore.topLevelItemCount())
                     if arvore.topLevelItem(i).text(0).startswith("Protegidos")).child(0)
    assert protegido.text(1) == "pasta da nuvem"
    # sem nada válido, o botão Confirmar fica desligado
    assert not d.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).isEnabled()


# --- miniaturas ----------------------------------------------------------------------------


def test_miniatura_pequena_e_com_cache(tmp_path, area, qtbot):
    foto = area / "Fotos" / "praia.png"
    mini = gerar_miniatura(foto, tmp_path / "cache")
    img = QImage(str(mini))
    assert max(img.width(), img.height()) <= 96 and img.width() == 96  # 400x300 → 96x72
    criada = mini.stat().st_mtime_ns
    assert gerar_miniatura(foto, tmp_path / "cache") == mini and mini.stat().st_mtime_ns == criada
    assert gerar_miniatura(area / "Downloads" / "cache.tmp", tmp_path / "cache") is None  # não é imagem


def test_carregador_responde_pelo_sinal(tmp_path, area, qtbot):
    c = CarregadorMiniaturas(tmp_path / "cache")
    with qtbot.waitSignal(c.pronta, timeout=5000) as sinal:
        c.pedir(str(area / "Fotos" / "praia.png"))
    assert sinal.args[1].width() == 96


def test_fechar_logo_depois_de_digitar_na_busca(janela, qtbot):
    """A busca espera 350 ms; fechar a janela antes disso não pode deixar o temporizador
    disparar com o índice fechado (era o travamento intermitente da suíte)."""
    janela.telas[1].busca.setText("praia")
    janela.close()
    qtbot.wait(600)  # o pytest-qt falha o teste se algo estourar no laço de eventos
    assert not janela.telas[1]._espera.isActive()
