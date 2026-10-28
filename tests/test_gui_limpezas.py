"""Tela Limpezas (Fase 7C.3): perfil falso, prévia simulada, quarentena de verdade só no tmp_path."""

import os
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from faxineiro import config, limpezas  # noqa: E402
from faxineiro.gui.app import Ambiente  # noqa: E402
from faxineiro.gui.miniaturas import CarregadorMiniaturas  # noqa: E402
from faxineiro.gui.tarefas import GerenteTarefas  # noqa: E402
from faxineiro.gui.telas.limpezas import TelaLimpezas  # noqa: E402
from faxineiro.indice import Indice  # noqa: E402

VELHO = time.time() - 3 * 24 * 3600


@pytest.fixture(autouse=True)
def caixas(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    vistas = []
    for nome in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, nome, lambda *a, **k: vistas.append(a[2] if len(a) > 2 else "")
                            or QMessageBox.StandardButton.Ok)
    return vistas


@pytest.fixture
def tela(tmp_path, qtbot, monkeypatch):
    perfil = (tmp_path / "Users" / "Carlos").resolve()
    for nome, tamanho in (("a.tmp", 1000), ("b.tmp", 2000)):
        arq = perfil / "AppData" / "Local" / "Temp" / nome
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_bytes(os.urandom(tamanho))
        os.utime(arq, (VELHO, VELHO))
    monkeypatch.setattr(config, "PASTA_DO_USUARIO", perfil)
    teste = tmp_path / "pasta_teste"
    teste.mkdir()
    banco = tmp_path / "dados" / "indice.sqlite"
    Indice(banco).fechar()
    amb = Ambiente(caminho_indice=banco, pasta=teste, limite=teste, gerente=GerenteTarefas(), leitura=Indice(banco),
                   miniaturas=CarregadorMiniaturas(tmp_path / "mini"), areas_pc=(perfil,),
                   local_quarentena=lambda arq: perfil / "_quarentena")
    t = TelaLimpezas(amb)
    t.medir = lambda **kw: limpezas.medir(perfil=perfil, abertos=lambda: {"msedge.exe"}, **kw)
    t.abertos = lambda: {"msedge.exe"}
    t.perfil = perfil
    qtbot.addWidget(t)
    yield t
    amb.gerente.esperar()
    amb.leitura.fechar()


def _medir(tela, qtbot):
    assert tela.atualizar()
    qtbot.waitUntil(lambda: not tela.amb.gerente.ocupado, timeout=20000)


def test_medir_mostra_e_bloqueia_navegador_aberto(tela, qtbot):
    _medir(tela, qtbot)
    linhas = {tela.tabela.item(i, 0).text(): i for i in range(tela.tabela.rowCount())}
    temp = linhas["Arquivos temporários (%TEMP%)"]
    assert tela.tabela.item(temp, 1).text() == "2.9 KB" and tela.tabela.item(temp, 3).text() == "pode limpar"
    assert [a.limpeza.id for a in tela.marcados()] == ["temp"]  # o resto: nada ou navegador
    assert tela.botao_limpar.isEnabled()


def test_sem_modo_pc_real_nao_limpa(tela, qtbot, caixas):
    _medir(tela, qtbot)
    assert not tela.limpar()
    assert "modo PC real" in caixas[-1]
    assert (tela.perfil / "AppData" / "Local" / "Temp" / "a.tmp").exists()


def test_limpar_com_previa_vai_para_a_quarentena(tela, qtbot, monkeypatch):
    _medir(tela, qtbot)
    tela.amb.pc_real = True
    vistos = []
    monkeypatch.setattr("faxineiro.gui.telas.limpezas.confirmar_previa", lambda plano, *a: vistos.append(plano) or True)
    assert tela.limpar()
    qtbot.waitUntil(lambda: not tela.amb.gerente.ocupado, timeout=20000)
    assert len(vistos[0].validos) == 2
    temp = tela.perfil / "AppData" / "Local" / "Temp"
    assert not (temp / "a.tmp").exists() and not (temp / "b.tmp").exists()
    assert len(list((tela.perfil / "_quarentena").rglob("*.tmp"))) == 2


def test_cancelar_a_previa_nao_mexe(tela, qtbot, monkeypatch):
    _medir(tela, qtbot)
    tela.amb.pc_real = True
    monkeypatch.setattr("faxineiro.gui.telas.limpezas.confirmar_previa", lambda *a: False)
    assert not tela.limpar()
    assert (tela.perfil / "AppData" / "Local" / "Temp" / "a.tmp").exists()
