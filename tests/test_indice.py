import sqlite3

import pytest

from faxineiro.indice import VERSAO_ESQUEMA, Indice, Registro


def _registro(caminho="C:/x/a.txt", tamanho=10, ns=1) -> Registro:
    return Registro(
        caminho=caminho, pasta_raiz="C:/x", nome="a.txt", extensao="txt", tamanho=tamanho,
        criado_em="2026-01-01T00:00:00", modificado_em="2026-01-01T00:00:00", modificado_ns=ns,
        tipo_real="texto", categoria="texto", extensao_confere=True,
    )


def test_cria_esquema_e_versao(indice):
    assert indice.con.execute("PRAGMA user_version").fetchone()[0] == VERSAO_ESQUEMA
    tabelas = {l[0] for l in indice.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"arquivos", "varreduras"} <= tabelas


def test_grava_com_aparelho_e_conectado(indice):
    v = indice.iniciar_varredura("C:/x", "pc", "agora")
    indice.gravar(_registro(), v, "agora")
    indice.confirmar()
    linha = indice.buscar("C:/x/a.txt")
    assert linha["aparelho"] == "pc"
    assert linha["conectado"] == 1
    assert linha["hash_completo"] is None


def test_atualiza_sem_duplicar(indice):
    v = indice.iniciar_varredura("C:/x", "pc", "agora")
    indice.gravar(_registro(tamanho=10), v, "agora")
    indice.gravar(_registro(tamanho=20, ns=2), v, "agora")
    indice.confirmar()
    assert indice.contar() == 1
    assert indice.buscar("C:/x/a.txt")["tamanho"] == 20
    assert indice.assinaturas("C:/x") == {"C:/x/a.txt": (20, 2)}


def test_remove_so_nao_vistos(indice):
    v1 = indice.iniciar_varredura("C:/x", "pc", "agora")
    indice.gravar(_registro("C:/x/a.txt"), v1, "agora")
    indice.gravar(_registro("C:/x/b.txt"), v1, "agora")
    v2 = indice.iniciar_varredura("C:/x", "pc", "agora")
    indice.marcar_visto(["C:/x/a.txt"], v2)
    assert indice.remover_nao_vistos("C:/x", v2) == 1
    assert indice.buscar("C:/x/a.txt") is not None
    assert indice.buscar("C:/x/b.txt") is None


def test_recusa_esquema_mais_novo(tmp_path):
    caminho = tmp_path / "futuro.sqlite"
    con = sqlite3.connect(caminho)
    con.execute(f"PRAGMA user_version = {VERSAO_ESQUEMA + 1}")
    con.close()
    with pytest.raises(RuntimeError):
        Indice(caminho)


def test_migra_banco_v1_para_a_versao_atual(tmp_path):
    from faxineiro.indice import _ESQUEMA

    caminho = tmp_path / "antigo.sqlite"
    con = sqlite3.connect(caminho)
    con.executescript(_ESQUEMA)
    con.execute("PRAGMA user_version = 1")
    con.execute(
        """INSERT INTO arquivos (caminho, pasta_raiz, nome, extensao, tamanho, modificado_ns,
               visto_em, indexado_em) VALUES ('C:/x/a.txt', 'C:/x', 'a.txt', 'txt', 3, 1, 1, 'ontem')"""
    )
    con.commit()
    con.close()

    with Indice(caminho) as i:
        assert i.con.execute("PRAGMA user_version").fetchone()[0] == VERSAO_ESQUEMA
        colunas = {l["name"] for l in i.con.execute("PRAGMA table_info(arquivos)")}
        assert "hash_em" in colunas
        tabelas = {l[0] for l in i.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"lotes", "operacoes"} <= tabelas
        assert i.contar() == 1


def test_tamanho_em_disco(indice):
    assert indice.tamanho_em_disco() > 0
