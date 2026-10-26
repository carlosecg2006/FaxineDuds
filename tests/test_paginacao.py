"""Consultas da interface: sempre em páginas, nunca a lista inteira."""

import pytest

from faxineiro.scanner import escanear

from .conftest import bytes_png


@pytest.fixture
def muitos(tmp_path, indice):
    raiz = tmp_path / "raiz"
    (raiz / "Fotos" / "Viagem").mkdir(parents=True)
    (raiz / "Docs").mkdir()
    for i in range(450):
        (raiz / f"arq_{i:03d}.txt").write_text(f"conteúdo {i}", encoding="utf-8")
    (raiz / "Fotos" / "praia.png").write_bytes(bytes_png())
    (raiz / "Fotos" / "Viagem" / "montanha.png").write_bytes(bytes_png() + b"1" * 1000)
    (raiz / "Docs" / "relatorio_100%_final.txt").write_text("x" * 5000, encoding="utf-8")
    (raiz / "Docs" / "notas_a.txt").write_text("nota", encoding="utf-8")
    escanear(raiz, indice)
    return raiz


def test_arquivos_da_pasta_em_paginas(muitos, indice):
    p1 = indice.arquivos_da_pasta(muitos, 200, 0)
    p3 = indice.arquivos_da_pasta(muitos, 200, 400)
    assert len(p1) == 200 and len(p3) == 50  # só os 450 soltos; subpastas não entram
    assert p1[0]["nome"] == "arq_000.txt"
    assert all("\\Fotos\\" not in l["caminho"] for l in p1 + p3)


def test_ordem_por_tamanho(muitos, indice):
    docs = indice.arquivos_da_pasta(muitos / "Docs", 10, 0, ordem="tamanho")
    assert docs[0]["nome"] == "relatorio_100%_final.txt"


def test_subpastas_com_tamanho_de_tudo_dentro(muitos, indice):
    subs = {s["nome"]: s for s in indice.subpastas(muitos)}
    assert set(subs) == {"Docs", "Fotos"}
    assert subs["Fotos"]["quantidade"] == 2  # conta a subpasta Viagem também
    assert [s["nome"] for s in indice.subpastas(muitos / "Fotos")] == ["Viagem"]


def test_tamanho_por_pasta_para_o_mapa(muitos, indice):
    blocos = {b["nome"]: b for b in indice.tamanho_por_pasta(muitos)}
    assert blocos["Fotos"]["pasta"] and blocos["Fotos"]["categoria"] == "imagem"
    assert not blocos["(arquivos soltos)"]["pasta"]
    assert blocos["(arquivos soltos)"]["quantidade"] == 450
    assert sum(b["bytes"] for b in blocos.values()) == sum(
        l["tamanho"] for l in indice.todos(str(muitos) + "\\"))


def test_busca_por_nome_e_descricao(muitos, indice):
    alvo = indice.buscar(str(muitos / "Docs" / "notas_a.txt"))
    indice.gravar_descricao(alvo["id"], "Anotações da aula de redes", "ia", False, "agora")
    indice.confirmar()
    assert [l["nome"] for l in indice.buscar_texto(muitos, "aula de redes")] == ["notas_a.txt"]
    assert [l["nome"] for l in indice.buscar_texto(muitos, "MONTANHA")] == ["montanha.png"]


def test_busca_escapa_curingas(muitos, indice):
    assert [l["nome"] for l in indice.buscar_texto(muitos, "100%")] == ["relatorio_100%_final.txt"]
    assert [l["nome"] for l in indice.buscar_texto(muitos, "s_a")] == ["notas_a.txt"]  # "_" literal


def test_busca_paginada(muitos, indice):
    assert len(indice.buscar_texto(muitos, "arq_", 200, 0)) == 200
    assert len(indice.buscar_texto(muitos, "arq_", 200, 400)) == 50
