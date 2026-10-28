"""Tela Programas (Fase 7C.2): lista falsa, ordenação, filtro e "Desinstalar" com um abridor falso."""

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from faxineiro.gui.app import Ambiente  # noqa: E402
from faxineiro.gui.miniaturas import CarregadorMiniaturas  # noqa: E402
from faxineiro.gui.tarefas import GerenteTarefas  # noqa: E402
from faxineiro.gui.telas.programas import TelaProgramas, _ha_quanto  # noqa: E402
from faxineiro.indice import Indice  # noqa: E402
from faxineiro.programas import CURSEFORGE, STEAM, Programa  # noqa: E402


@pytest.fixture(autouse=True)
def caixas(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    vistas = []
    for nome in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, nome, lambda *a, **k: vistas.append(a[2] if len(a) > 2 else "")
                            or QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: pytest.fail("pergunta sem resposta no teste"))
    return vistas


@pytest.fixture
def tela(tmp_path, qtbot):
    teste = tmp_path / "pasta_teste"
    teste.mkdir()
    banco = tmp_path / "dados" / "indice.sqlite"
    Indice(banco).fechar()
    amb = Ambiente(caminho_indice=banco, pasta=teste, limite=teste, gerente=GerenteTarefas(), leitura=Indice(banco),
                   miniaturas=CarregadorMiniaturas(tmp_path / "mini"))
    t = TelaProgramas(amb)
    lista = [
        Programa("Git", tamanho=300, instalado_em="2026-07-04", ultimo_uso="2026-10-01",
                 desinstalador='"C:\\Git\\unins000.exe" /S', pasta=str(tmp_path)),
        Programa("FL Studio", tamanho=5000, desinstalador="C:\\FL\\uninstall.exe"),
        Programa("Dota 2", origem=STEAM, tamanho=900, desinstalador="steam://uninstall/570"),
        Programa("Minecraft — Story", origem=CURSEFORGE, como="Remova pelo app do CurseForge."),
        Programa("Obsidian", pasta="E:\\obs", pasta_existe=False, desinstalador="E:\\obs\\u.exe"),
    ]
    t.listar = lambda **kw: lista
    t.chamadas = []
    t.abrir = lambda arquivo, args: t.chamadas.append((arquivo, args))
    qtbot.addWidget(t)
    yield t
    amb.gerente.esperar()
    amb.leitura.fechar()


def _carregar(tela, qtbot):
    assert tela.atualizar()
    qtbot.waitUntil(lambda: not tela.amb.gerente.ocupado, timeout=20000)


def _selecionar(tela, nome):
    for linha in range(tela.tabela.rowCount()):
        if tela.tabela.item(linha, 0).text().startswith(nome):
            tela.tabela.selectRow(linha)
            return
    pytest.fail(nome)


def test_lista_ordenada_por_tamanho_e_avisa_pasta_sumida(tela, qtbot):
    _carregar(tela, qtbot)
    nomes = [tela.tabela.item(i, 0).text() for i in range(tela.tabela.rowCount())]
    assert nomes[:3] == ["FL Studio", "Dota 2", "Git"]
    assert any("pasta não encontrada" in n for n in nomes)
    assert "5 programas" in tela.resumo.text() and "1 com a pasta não encontrada" in tela.resumo.text()


def test_filtro(tela, qtbot):
    _carregar(tela, qtbot)
    tela.busca.setText("git")
    visiveis = [tela.tabela.item(i, 0).text() for i in range(tela.tabela.rowCount()) if not tela.tabela.isRowHidden(i)]
    assert visiveis == ["Git"]


def test_desinstalar_pergunta_e_abre_o_oficial(tela, qtbot):
    _carregar(tela, qtbot)
    _selecionar(tela, "Git")
    assert not tela.desinstalar(confirmar=lambda: False)
    assert tela.chamadas == []  # cancelou: nada aberto
    assert tela.desinstalar(confirmar=lambda: True)
    assert tela.chamadas == [("C:\\Git\\unins000.exe", "/S")]


def test_desinstalar_steam_e_curseforge(tela, qtbot, caixas):
    _carregar(tela, qtbot)
    _selecionar(tela, "Dota 2")
    assert tela.desinstalar(confirmar=lambda: True)
    assert tela.chamadas == [("steam://uninstall/570", "")]
    _selecionar(tela, "Minecraft")
    assert not tela.desinstalar(confirmar=lambda: pytest.fail("não pergunta: não há desinstalador"))
    assert "CurseForge" in caixas[-1] and len(tela.chamadas) == 1


def test_apps_da_loja_abre_configuracoes(tela):
    tela.botao_loja.click()
    assert tela.chamadas == [("ms-settings:appsfeatures", "")]


def test_ha_quanto():
    from datetime import date

    hoje = date(2026, 10, 28)
    assert _ha_quanto("2026-10-28", hoje) == "hoje"
    assert _ha_quanto("2026-10-01", hoje) == "há 27 dias"
    assert _ha_quanto("2026-03-01", hoje) == "há 8 meses"
    assert _ha_quanto("2023-01-01", hoje) == "há 3 anos"
