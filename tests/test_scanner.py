import os

import pytest

from faxineiro.__main__ import main
from faxineiro.config import Bloqueios, dentro_da_pasta_teste
from faxineiro.scanner import escanear
from faxineiro.tipos import detectar_tipo


class DetectorContador:
    """Envolve detectar_tipo e conta quantas vezes o conteúdo foi lido."""

    def __init__(self):
        self.chamadas = 0

    def __call__(self, caminho):
        self.chamadas += 1
        return detectar_tipo(caminho)


def test_primeira_varredura_indexa_tudo(pasta, indice):
    p = escanear(pasta, indice)
    assert (p.varridos, p.novos, p.alterados, p.iguais, p.removidos) == (5, 5, 0, 0, 0)
    linha = indice.buscar(str(pasta / "fotos" / "praia.png"))
    assert linha["nome"] == "praia.png"
    assert linha["extensao"] == "png"
    assert linha["tipo_real"] == "png"
    assert linha["categoria"] == "imagem"
    assert linha["aparelho"] == "pc"
    assert linha["conectado"] == 1
    assert linha["tamanho"] > 0
    assert linha["criado_em"] and linha["modificado_em"]


def test_segunda_varredura_nao_rele_nada(pasta, indice):
    escanear(pasta, indice)
    detector = DetectorContador()
    p = escanear(pasta, indice, detector=detector)
    assert (p.novos, p.alterados, p.iguais, p.removidos) == (0, 0, 5, 0)
    assert detector.chamadas == 0


def test_arquivo_alterado(pasta, indice):
    escanear(pasta, indice)
    notas = pasta / "notas.txt"
    notas.write_text("conteúdo novo e maior que antes\n", encoding="utf-8")
    st = notas.stat()
    os.utime(notas, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    detector = DetectorContador()
    p = escanear(pasta, indice, detector=detector)
    assert (p.novos, p.alterados, p.iguais) == (0, 1, 4)
    assert detector.chamadas == 1


def test_arquivo_novo_e_sumido(pasta, indice):
    escanear(pasta, indice)
    (pasta / "docs" / "contrato.pdf").unlink()  # só na pasta temporária do teste
    (pasta / "novo.txt").write_text("oi", encoding="utf-8")
    p = escanear(pasta, indice)
    assert (p.novos, p.removidos) == (1, 1)
    assert indice.buscar(str(pasta / "docs" / "contrato.pdf")) is None
    assert indice.contar() == 5


def test_extensao_errada_fica_registrada(pasta, indice):
    (pasta / "disfarce.jpg").write_bytes((pasta / "docs" / "contrato.pdf").read_bytes())
    escanear(pasta, indice)
    linha = indice.buscar(str(pasta / "disfarce.jpg"))
    assert linha["tipo_real"] == "pdf"
    assert linha["extensao_confere"] == 0


def test_pasta_bloqueada_por_nome(pasta, indice):
    (pasta / "_quarentena").mkdir()
    (pasta / "_quarentena" / "x.txt").write_text("não indexar", encoding="utf-8")
    (pasta / "AppData").mkdir()
    (pasta / "AppData" / "y.txt").write_text("não indexar", encoding="utf-8")
    p = escanear(pasta, indice)
    assert p.novos == 5
    assert p.ignorados == 2
    assert len(p.pastas_ignoradas) == 2


def test_pasta_bloqueada_por_caminho(pasta, indice):
    bloqueios = Bloqueios(caminhos=[str(pasta / "fotos")], nomes=[])
    p = escanear(pasta, indice, bloqueios=bloqueios)
    assert p.novos == 3
    assert indice.buscar(str(pasta / "fotos" / "praia.png")) is None


def test_bloqueios_padrao():
    b = Bloqueios()
    assert b.bloqueada(r"C:\Windows")
    assert b.bloqueada(r"c:\windows\System32")
    assert b.bloqueada(r"C:\Program Files (x86)\Steam")
    assert b.bloqueada(r"C:\Users\carlos\AppData")
    assert not b.bloqueada(r"C:\Users\carlos\Documentos")
    assert not b.bloqueada(r"C:\WindowsBackup")


def test_progresso_e_chamado(pasta, indice):
    eventos = []
    escanear(pasta, indice, ao_progredir=lambda p: eventos.append(p.terminou))
    assert eventos and eventos[-1] is True


def test_varredura_fica_registrada(pasta, indice):
    escanear(pasta, indice)
    linha = indice.con.execute("SELECT * FROM varreduras").fetchone()
    assert linha["novos"] == 5 and linha["fim"] is not None


@pytest.mark.skipif(os.name != "nt", reason="limite de 260 caracteres é do Windows")
def test_caminho_maior_que_260_nao_trava(tmp_path, indice):
    """Sem LongPathsEnabled o Windows não abre a pasta: o scanner avisa e segue (ver Fase 7)."""
    base = tmp_path / "longo"
    base.mkdir()
    (base / "curto.txt").write_text("ok", encoding="utf-8")
    fundo = base
    while len(str(fundo)) < 300:
        fundo = fundo / ("pasta_de_nome_comprido_" + "x" * 20)
    os.makedirs("\\\\?\\" + str(fundo))  # \\?\ permite criar mesmo sem LongPathsEnabled
    with open("\\\\?\\" + str(fundo / "fundo.txt"), "w", encoding="utf-8") as f:
        f.write("lá no fundo")

    p = escanear(base, indice)
    assert indice.buscar(str(base / "curto.txt")) is not None
    indexou_o_fundo = indice.buscar(str(fundo / "fundo.txt")) is not None
    avisou = any("Caminho longo demais" in a for a in p.avisos)
    assert indexou_o_fundo or avisou  # com LongPathsEnabled=1 indexa; sem, avisa claramente


def test_pasta_inexistente(tmp_path, indice):
    with pytest.raises(NotADirectoryError):
        escanear(tmp_path / "nao_existe", indice)


def test_trava_pasta_teste(tmp_path):
    base = tmp_path / "pasta_teste"
    (base / "sub").mkdir(parents=True)
    assert dentro_da_pasta_teste(base, base)
    assert dentro_da_pasta_teste(base / "sub", base)
    assert not dentro_da_pasta_teste(tmp_path, base)
    assert not dentro_da_pasta_teste(tmp_path / "pasta_teste_falsa", base)


def test_cli_recusa_fora_da_pasta_teste(tmp_path, capsys):
    codigo = main(["escanear", str(tmp_path), "--indice", str(tmp_path / "i.sqlite")])
    assert codigo == 2
    assert "Recusado" in capsys.readouterr().err
    assert not (tmp_path / "i.sqlite").exists()
