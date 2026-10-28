"""Interface da Fase 7B: modo PC real, seletor de pasta e "Mover para outra unidade".

O "PC real" aqui é simulado: uma pasta "pc" dentro do tmp_path, com duas "unidades" (C e D).
"""

import random
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from faxineiro.gui.app import Ambiente, Janela  # noqa: E402
from faxineiro.gui.miniaturas import CarregadorMiniaturas  # noqa: E402
from faxineiro.gui.tarefas import GerenteTarefas  # noqa: E402
from faxineiro.hashes import Hasher  # noqa: E402
from faxineiro.indice import Indice  # noqa: E402
from faxineiro.scanner import escanear  # noqa: E402


def _criar(caminho: Path, conteudo: bytes) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(conteudo)
    return caminho


@pytest.fixture(autouse=True)
def caixas(monkeypatch):
    """Nenhuma caixa de mensagem pode travar o teste esperando um clique: só registra o texto."""
    from PySide6.QtWidgets import QMessageBox

    vistas = []
    for nome in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, nome, lambda *a, **k: vistas.append(a[2] if len(a) > 2 else "")
                            or QMessageBox.StandardButton.Ok)
    return vistas


@pytest.fixture
def pc(tmp_path):
    teste, c, d = tmp_path / "pasta_teste", tmp_path / "C", tmp_path / "D"
    _criar(teste / "a.txt", b"teste")
    _criar(c / "Videos" / "aula.mp4", random.Random(1).randbytes(300_000))
    _criar(c / "Samples" / "kick.wav", random.Random(2).randbytes(5000))
    (d / "Arquivo").mkdir(parents=True)
    return teste.resolve(), c.resolve(), d.resolve()


@pytest.fixture
def amb(tmp_path, pc, qtbot):
    teste, c, d = pc
    banco = tmp_path / "dados" / "indice.sqlite"
    with Indice(banco) as i:
        for pasta in pc:
            escanear(pasta, i)

    def unidade(caminho):
        p = Path(caminho).resolve()
        return next((nome for nome, raiz in (("C:", c), ("D:", d), ("T:", teste)) if p == raiz or raiz in p.parents), "?")

    raizes = {"C:": c, "D:": d, "T:": teste}
    a = Ambiente(caminho_indice=banco, pasta=teste, limite=teste, gerente=GerenteTarefas(), leitura=Indice(banco),
                 miniaturas=CarregadorMiniaturas(tmp_path / "mini"), areas_pc=(c, d), unidade=unidade,
                 local_quarentena=lambda arq: raizes[unidade(arq)] / "_quarentena")
    yield a
    a.gerente.esperar()
    a.leitura.fechar()


@pytest.fixture
def janela(amb, qtbot):
    j = Janela(amb)
    qtbot.addWidget(j)
    yield j
    j.close()  # antes do `amb` fechar o índice: para os temporizadores (busca do Explorador, RAM da IA)


def _esperar(qtbot, amb):
    qtbot.waitUntil(lambda: not amb.gerente.ocupado, timeout=20000)


def test_modo_pc_real_comeca_desligado_e_pede_pc_real(janela, amb, pc):
    assert not amb.pc_real and amb.areas == (amb.limite,)
    assert janela.faixa.isHidden()
    assert not janela.ligar_pc_real(True, perguntar_texto=lambda: ("pc real", True))  # tem que ser exato
    assert not amb.pc_real and not janela.acao_pc_real.isChecked()
    assert janela.ligar_pc_real(True, perguntar_texto=lambda: ("PC REAL", True))
    assert amb.pc_real and amb.areas == (amb.limite, pc[1], pc[2])
    assert not janela.faixa.isHidden() and "MODO PC REAL" in janela.windowTitle()
    janela.ligar_pc_real(False)  # desligar não pergunta
    assert not amb.pc_real and janela.faixa.isHidden()


def test_seletor_troca_a_pasta_das_telas(janela, amb, pc, caixas):
    teste, c, d = pc
    assert janela.trocar_pasta(c)
    assert amb.pasta == c and janela.telas[1].pasta_atual == c
    assert not janela.trocar_pasta(Path(pc[0]).parent / "fora")  # fora das áreas
    (c / "AppData").mkdir()
    assert not janela.trocar_pasta(c / "AppData")  # pasta bloqueada
    assert amb.pasta == c and len(caixas) == 2


def test_sem_modo_pc_real_a_previa_recusa(janela, amb, pc, monkeypatch):
    teste, c, d = pc
    previas = []
    monkeypatch.setattr("faxineiro.gui.mover.confirmar_previa", lambda plano, *a, **k: previas.append(plano))
    janela.trocar_pasta(c)
    exp = janela.telas[1]
    exp.mover_pasta_para_unidade(c / "Videos", escolher_destino=lambda _: str(d / "Arquivo"))
    assert previas and previas[0].validos == []
    assert "ligue o modo PC real" in previas[0].passos[0].problema
    assert (c / "Videos" / "aula.mp4").exists()


def test_explorador_move_pasta_para_outra_unidade(janela, amb, pc, qtbot, monkeypatch):
    teste, c, d = pc
    previas = []
    monkeypatch.setattr("faxineiro.gui.mover.confirmar_previa",
                        lambda plano, *a, **k: previas.append(plano) or True)
    janela.ligar_pc_real(True, perguntar_texto=lambda: ("PC REAL", True))
    janela.trocar_pasta(c)
    antes = Hasher().completo(c / "Videos" / "aula.mp4")
    assert janela.telas[1].mover_pasta_para_unidade(c / "Videos", escolher_destino=lambda _: str(d / "Arquivo"))
    _esperar(qtbot, amb)
    assert Hasher().completo(d / "Arquivo" / "Videos" / "aula.mp4") == antes
    assert not (c / "Videos").exists()
    texto = " ".join(previas[0].avisos)
    assert "ESVAZIAR" in texto and "FL Studio" in texto
    assert "liberado ao esvaziar" in janela.statusBar().currentMessage()
    janela.telas[4].atualizar()  # tela Quarentena mostra a quarentena do C
    assert str(c / "_quarentena") in janela.telas[4].resumo.text()


def test_pesados_move_os_marcados(janela, amb, pc, qtbot, monkeypatch):
    teste, c, d = pc
    monkeypatch.setattr("faxineiro.gui.mover.confirmar_previa", lambda *a, **k: True)
    janela.ligar_pc_real(True, perguntar_texto=lambda: ("PC REAL", True))
    janela.trocar_pasta(c)
    faxina = janela.telas[2]
    faxina.minimo.setValue(0.1)  # 100 KB
    faxina.analisar()
    _esperar(qtbot, amb)
    faxina.abas.setCurrentWidget(faxina.pesados)
    assert faxina.botao_mover.isVisibleTo(faxina)
    item = faxina.pesados.topLevelItem(0)
    assert item.text(0).endswith("aula.mp4")
    item.setCheckState(0, item.checkState(0).__class__.Checked)
    assert faxina.mover_pesados(escolher_destino=lambda _: str(d / "Arquivo"))
    _esperar(qtbot, amb)
    assert (d / "Arquivo" / "aula.mp4").exists() and not (c / "Videos" / "aula.mp4").exists()


def test_quarentena_esvazia_so_a_unidade_escolhida(janela, amb, pc, qtbot, monkeypatch):
    teste, c, d = pc
    monkeypatch.setattr("faxineiro.gui.telas.quarentena.confirmar_previa", lambda plano, *a, **k: True)
    monkeypatch.setattr("faxineiro.gui.telas.quarentena.confirmar_esvaziar", lambda *a, **k: True)
    janela.ligar_pc_real(True, perguntar_texto=lambda: ("PC REAL", True))
    q = amb.quarentena(amb.leitura)
    q.executar(q.planejar_mover([c / "Samples" / "kick.wav", teste / "a.txt"]))
    tela = janela.telas[4]
    tela.atualizar()
    opcoes = [tela.unidade_esvaziar.itemData(i) for i in range(tela.unidade_esvaziar.count())]
    assert opcoes == [None, "C:", "T:"]
    tela.unidade_esvaziar.setCurrentIndex(opcoes.index("C:"))
    assert tela.esvaziar()
    _esperar(qtbot, amb)
    restantes = amb.leitura.itens_na_quarentena()
    assert [Path(o["origem"]).name for o in restantes] == ["a.txt"]  # a do outro "disco" ficou


def test_explorador_manda_pasta_inteira_para_quarentena(janela, amb, pc, qtbot, monkeypatch):
    teste, c, d = pc
    monkeypatch.setattr("faxineiro.gui.telas.explorador.confirmar_previa", lambda *a, **k: True)
    janela.ligar_pc_real(True, perguntar_texto=lambda: ("PC REAL", True))
    janela.trocar_pasta(c)
    assert janela.telas[1].mandar_pasta_para_quarentena(c / "Samples")
    _esperar(qtbot, amb)
    assert not (c / "Samples").exists()
    assert len(amb.leitura.itens_na_quarentena()) == 1


def test_esvaziar_sem_modo_pc_real_explica_o_motivo(janela, amb, pc, caixas):
    """Bug: com o modo desligado, "Só o C:" dizia "Nada a apagar" mesmo com arquivos lá."""
    teste, c, d = pc
    janela.ligar_pc_real(True, perguntar_texto=lambda: ("PC REAL", True))
    q = amb.quarentena(amb.leitura)
    q.executar(q.planejar_mover([c / "Samples" / "kick.wav"]))
    janela.ligar_pc_real(False)
    tela = janela.telas[4]
    tela.atualizar()
    tela.unidade_esvaziar.setCurrentIndex(tela.unidade_esvaziar.findData("C:"))
    assert not tela.esvaziar()
    assert caixas and "ligue o modo PC real" in caixas[-1] and "1 item(ns)" in caixas[-1]
    assert len(amb.leitura.itens_na_quarentena()) == 1  # nada apagado
