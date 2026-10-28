"""Tela Sistema (Fase 7C.1): mede uma "unidade" falsa do tmp_path, guarda em dados/ e mostra com selos."""

from functools import partial
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from faxineiro import sistema  # noqa: E402
from faxineiro.gui.app import Ambiente, Janela  # noqa: E402
from faxineiro.gui.miniaturas import CarregadorMiniaturas  # noqa: E402
from faxineiro.gui.tarefas import GerenteTarefas  # noqa: E402
from faxineiro.gui.telas.sistema import TelaSistema  # noqa: E402
from faxineiro.indice import Indice  # noqa: E402


def _criar(caminho: Path, tamanho: int) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(b"x" * tamanho)


@pytest.fixture
def amb(tmp_path, qtbot):
    teste = tmp_path / "pasta_teste"
    teste.mkdir()
    banco = tmp_path / "dados" / "indice.sqlite"
    Indice(banco).fechar()
    a = Ambiente(caminho_indice=banco, pasta=teste, limite=teste, gerente=GerenteTarefas(), leitura=Indice(banco),
                 miniaturas=CarregadorMiniaturas(tmp_path / "mini"))
    yield a
    a.gerente.esperar()
    a.leitura.fechar()


@pytest.fixture
def tela(amb, tmp_path, qtbot):
    raiz = tmp_path / "C"
    perfil = raiz / "Users" / "Carlos"
    _criar(raiz / "Windows" / "Temp" / "a.tmp", 500)
    _criar(raiz / "Program Files" / "Jogo" / "jogo.exe", 4000)
    _criar(perfil / "AppData" / "Local" / "Temp" / "b.tmp", 300)
    t = TelaSistema(amb)
    t.medir = lambda unidade, **kw: sistema.medir_sistema(raiz, perfil=perfil, minimo=100,
                                                          uso=lambda r: (10**9, 10**6, 0), **kw)
    qtbot.addWidget(t)
    return t


def _linhas(arvore):
    def todas(item):
        yield item
        for i in range(item.childCount()):
            yield from todas(item.child(i))

    for i in range(arvore.topLevelItemCount()):
        yield from todas(arvore.topLevelItem(i))


def test_sem_medicao_pede_para_medir(tela):
    assert "Ainda não medido" in tela.resumo.text()
    assert tela.arvore.topLevelItemCount() == 0


def test_medir_mostra_selos_e_guarda(tela, amb, qtbot, tmp_path):
    assert tela.medir_agora()
    qtbot.waitUntil(lambda: not amb.gerente.ocupado, timeout=20000)
    linhas = {l.text(0).split("  ")[0]: l for l in _linhas(tela.arvore)}
    assert linhas["Jogo"].text(2) == sistema.DESINSTALADOR
    assert linhas["Temp"].text(2) == sistema.SEGURO
    assert "Program Files" in "".join(linhas)
    salvo = tmp_path / "dados" / f"sistema_{tela.unidade.currentData()[0]}.json"
    assert salvo.exists()
    # abrir de novo mostra a medição guardada, sem medir
    outra = TelaSistema(amb)
    qtbot.addWidget(outra)
    assert outra.arvore.topLevelItemCount() == tela.arvore.topLevelItemCount()
    assert "medido em" in outra.resumo.text()


def test_cancelar_nao_guarda(tela, amb, qtbot, tmp_path):
    tela.medir = partial(lambda unidade, **kw: sistema.RaioXSistema("C:\\", "2026-10-28T10:00:00", 0, [], cancelado=True))
    assert tela.medir_agora()
    qtbot.waitUntil(lambda: not amb.gerente.ocupado, timeout=20000)
    assert not list((tmp_path / "dados").glob("sistema_*.json"))


def test_janela_tem_a_tela_sistema(amb, qtbot):
    j = Janela(amb)
    qtbot.addWidget(j)
    nomes = [j.lateral.item(i).text() for i in range(j.lateral.count())]
    assert "Sistema" in nomes
    j.close()
