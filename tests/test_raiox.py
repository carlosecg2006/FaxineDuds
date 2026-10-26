import os
import random

import pytest

from faxineiro import raiox
from faxineiro.__main__ import main
from faxineiro.config import Bloqueios
from faxineiro.hashes import TAMANHO_PARCIAL, Hasher
from faxineiro.scanner import escanear


def _bytes(semente: int, tamanho: int) -> bytes:
    """Bytes "aleatórios" mas sempre os mesmos (teste estável: nunca imitam outro formato por acaso)."""
    return random.Random(semente).randbytes(tamanho)


def _avancar_mtime(caminho, segundos=5):
    st = caminho.stat()
    os.utime(caminho, ns=(st.st_atime_ns, st.st_mtime_ns + segundos * 1_000_000_000))


@pytest.fixture
def bagunca(tmp_path):
    """Pasta com duplicados, quase-duplicados, lixo e pastas vazias."""
    raiz = tmp_path / "bagunca"
    (raiz / "a").mkdir(parents=True)
    (raiz / "b" / "c").mkdir(parents=True)
    foto = _bytes(1, 5000)
    (raiz / "foto.jpg").write_bytes(foto)
    (raiz / "a" / "foto (1).jpg").write_bytes(foto)
    (raiz / "b" / "c" / "foto copia.jpg").write_bytes(foto)
    # Grandes, mesmo tamanho, começo igual, só o último byte diferente.
    comum = _bytes(2, TAMANHO_PARCIAL * 4)
    (raiz / "video1.bin").write_bytes(comum + b"1")
    (raiz / "video2.bin").write_bytes(comum + b"2")
    (raiz / "unico.txt").write_text("só existe um de mim", encoding="utf-8")
    (raiz / "vazio.txt").write_bytes(b"")
    (raiz / "~$trabalho.docx").write_bytes(b"rascunho do word")
    (raiz / "download.crdownload").write_bytes(b"x" * 100)
    (raiz / "Thumbs.db").write_bytes(b"miniaturas")
    (raiz / "pasta_vazia").mkdir()
    (raiz / "so_subpastas" / "sub1" / "sub2").mkdir(parents=True)
    return raiz


@pytest.fixture
def escaneada(bagunca, indice):
    escanear(bagunca, indice)
    return bagunca


def _nomes(linhas):
    return sorted(os.path.basename(l["caminho"]) for l in linhas)


def test_acha_grupo_de_tres_copias(escaneada, indice):
    r = raiox.encontrar_duplicados(indice, escaneada)
    assert len(r.grupos) == 1
    g = r.grupos[0]
    assert _nomes(g.arquivos) == ["foto (1).jpg", "foto copia.jpg", "foto.jpg"]
    assert g.recuperavel == 5000 * 2
    assert r.recuperavel == 10000
    assert "BLAKE3" in g.motivo and "5000 bytes" in g.motivo


def test_quase_iguais_nao_sao_duplicados(escaneada, indice):
    """Mesmo tamanho e mesmo começo, mas fim diferente: não é duplicado (sem amostragem)."""
    r = raiox.encontrar_duplicados(indice, escaneada)
    todos = [os.path.basename(a["caminho"]) for g in r.grupos for a in g.arquivos]
    assert "video1.bin" not in todos and "video2.bin" not in todos
    l1 = indice.buscar(str(escaneada / "video1.bin"))
    l2 = indice.buscar(str(escaneada / "video2.bin"))
    assert l1["hash_parcial"] == l2["hash_parcial"]
    assert l1["hash_completo"] != l2["hash_completo"]


def test_tamanho_unico_nem_e_lido(escaneada, indice):
    hasher = Hasher()
    raiox.encontrar_duplicados(indice, escaneada, hasher=hasher)
    # Só as 3 fotos + os 2 vídeos dividem tamanho: 5 parciais, 2 completos (vídeos).
    assert hasher.parciais == 5
    assert hasher.completos == 2
    assert indice.buscar(str(escaneada / "unico.txt"))["hash_parcial"] is None


def test_segunda_vez_usa_cache(escaneada, indice):
    raiox.encontrar_duplicados(indice, escaneada)
    hasher = Hasher()
    r = raiox.encontrar_duplicados(indice, escaneada, hasher=hasher)
    assert (hasher.parciais, hasher.completos, hasher.bytes_lidos) == (0, 0, 0)
    assert len(r.grupos) == 1


def test_arquivo_alterado_e_reescaneado_e_relido(escaneada, indice):
    raiox.encontrar_duplicados(indice, escaneada)
    alvo = escaneada / "a" / "foto (1).jpg"
    alvo.write_bytes(_bytes(3, 5000))
    _avancar_mtime(alvo)
    escanear(escaneada, indice)
    hasher = Hasher()
    r = raiox.encontrar_duplicados(indice, escaneada, hasher=hasher)
    assert hasher.parciais == 1
    assert _nomes(r.grupos[0].arquivos) == ["foto copia.jpg", "foto.jpg"]


def test_indice_desatualizado_gera_aviso(escaneada, indice):
    alvo = escaneada / "a" / "foto (1).jpg"
    alvo.write_bytes(_bytes(3, 5000))
    _avancar_mtime(alvo)  # mudou, mas ninguém rodou escanear
    r = raiox.encontrar_duplicados(indice, escaneada)
    assert str(alvo) in r.desatualizados
    assert _nomes(r.grupos[0].arquivos) == ["foto copia.jpg", "foto.jpg"]


def test_sugere_manter_caminho_mais_curto_no_empate(escaneada, indice):
    g = raiox.encontrar_duplicados(indice, escaneada).grupos[0]
    if len({a["criado_em"] for a in g.arquivos}) == 1:
        assert os.path.basename(g.manter["caminho"]) == "foto.jpg"


def test_sugere_manter_o_mais_antigo():
    arquivos = [
        {"caminho": r"C:\a\curto.jpg", "criado_em": "2026-05-01T10:00:00"},
        {"caminho": r"C:\a\b\c\caminho_bem_longo.jpg", "criado_em": "2020-01-01T10:00:00"},
    ]
    assert raiox._sugerir_manter(arquivos)["caminho"].endswith("caminho_bem_longo.jpg")


def test_pesados_respeita_minimo(escaneada, indice):
    assert raiox.pesados(indice, escaneada) == []  # padrão 100 MB: nada aqui é pesado
    assert _nomes(raiox.pesados(indice, escaneada, minimo=200_000)) == ["video1.bin", "video2.bin"]
    assert _nomes(raiox.pesados(indice, escaneada, minimo=5000)) == [
        "foto (1).jpg", "foto copia.jpg", "foto.jpg", "video1.bin", "video2.bin"]


def test_minimo_da_linha_de_comando():
    import argparse

    from faxineiro.__main__ import minimo_pesado
    from faxineiro.config import MB, PESADO_MINIMO, PESADO_MINIMO_TESTE

    assert PESADO_MINIMO == 100 * MB
    assert minimo_pesado(argparse.Namespace(minimo_mb=None, teste=False)) == PESADO_MINIMO
    assert minimo_pesado(argparse.Namespace(minimo_mb=None, teste=True)) == PESADO_MINIMO_TESTE
    assert minimo_pesado(argparse.Namespace(minimo_mb=0.5, teste=True)) == MB // 2


def test_pesados_e_categorias(escaneada, indice):
    grandes = raiox.pesados(indice, escaneada, 2, minimo=0)
    assert _nomes(grandes) == ["video1.bin", "video2.bin"]
    cats = {c["categoria"]: c["quantidade"] for c in raiox.totais_por_categoria(indice, escaneada)}
    assert cats["outro"] >= 5  # bytes aleatórios (fotos e vídeos falsos) caem em "outro"
    assert cats["texto"] >= 1
    assert sum(cats.values()) == indice.contar()


def test_lixo(escaneada, indice):
    lx = raiox.lixo(indice, escaneada)
    assert _nomes(lx.vazios) == ["vazio.txt"]
    assert _nomes(lx.temporarios) == ["Thumbs.db", "download.crdownload", "~$trabalho.docx"]
    assert lx.recuperavel == len(b"rascunho do word") + 100 + len(b"miniaturas")


def test_extensao_errada(escaneada, indice):
    (escaneada / "disfarce.png").write_text("na verdade sou texto", encoding="utf-8")
    escanear(escaneada, indice)
    errados = _nomes(raiox.extensao_errada(indice, escaneada))
    assert errados == ["disfarce.png"]
    # Não entram: bytes aleatórios (tipo desconhecido), temporários (já são lixo)
    # e extensões que não julgamos (.bin, .db, .crdownload).


def test_pastas_vazias(bagunca):
    vazias = [os.path.relpath(p, bagunca) for p in raiox.pastas_vazias(bagunca)]
    assert vazias == ["pasta_vazia", "so_subpastas"]


def test_pastas_vazias_ignora_bloqueadas(bagunca):
    (bagunca / "_quarentena").mkdir()
    vazias = [os.path.relpath(p, bagunca) for p in raiox.pastas_vazias(bagunca, Bloqueios())]
    assert "_quarentena" not in vazias


def test_raiox_nao_altera_nenhum_arquivo(escaneada, indice):
    antes = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in escaneada.rglob("*") if p.is_file()}
    raiox.encontrar_duplicados(indice, escaneada)
    raiox.lixo(indice, escaneada)
    raiox.pastas_vazias(escaneada)
    depois = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in escaneada.rglob("*") if p.is_file()}
    assert antes == depois


def test_subpasta_filtra_resultados(escaneada, indice):
    r = raiox.encontrar_duplicados(indice, escaneada / "b")
    assert r.grupos == []  # só há 1 foto dentro de b/


def test_cli_raiox_recusa_fora_da_pasta_teste(tmp_path, capsys):
    assert main(["raiox", str(tmp_path), "--indice", str(tmp_path / "i.sqlite")]) == 2


def test_cli_raiox_exige_escanear_antes(monkeypatch, tmp_path, capsys):
    base = tmp_path / "pasta_teste"
    base.mkdir()
    monkeypatch.setattr("faxineiro.__main__.dentro_da_pasta_teste", lambda p: True)
    assert main(["raiox", str(base), "--indice", str(tmp_path / "i.sqlite")]) == 1
    assert "ainda não foi escaneada" in capsys.readouterr().err
