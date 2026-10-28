"""Fase 7C.3 — Limpezas seguras. Perfil falso no tmp_path: o AppData real nunca é tocado."""

import os
import time
from pathlib import Path

import pytest

from faxineiro import config, limpezas
from faxineiro.indice import Indice
from faxineiro.protecoes import cache_liberado
from faxineiro.quarentena import Quarentena

AGORA = time.time()
VELHO = AGORA - 3 * 24 * 3600


def _criar(caminho: Path, tamanho: int = 100, mtime: float = VELHO) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(os.urandom(tamanho))
    os.utime(caminho, (mtime, mtime))
    return caminho


@pytest.fixture
def perfil(tmp_path, monkeypatch):
    p = (tmp_path / "Users" / "Carlos").resolve()
    local = p / "AppData" / "Local"
    _criar(local / "Temp" / "velho.tmp", 1000)
    _criar(local / "Temp" / "novo.tmp", 10, mtime=AGORA)
    _criar(local / "Temp" / "instalador_antigo" / "a.bin", 2000)
    _criar(local / "Temp" / "sessao_aberta" / "antigo.log", 3000)
    _criar(local / "Temp" / "sessao_aberta" / "agora.log", 5, mtime=AGORA)  # deixa a pasta inteira
    _criar(local / "Google" / "Chrome" / "User Data" / "Default" / "Cache" / "Cache_Data" / "f_1", 4000)
    _criar(local / "Google" / "Chrome" / "User Data" / "Profile 1" / "Code Cache" / "js" / "x", 500)
    _criar(local / "Google" / "Chrome" / "User Data" / "Default" / "Login Data", 77)  # senhas: nunca
    _criar(local / "npm-cache" / "_cacache" / "index", 600)
    _criar(local / "Discord" / "settings.json", 50)  # fora da lista
    monkeypatch.setattr(config, "PASTA_DO_USUARIO", p)
    return p


def _q(tmp_path, perfil):
    indice = Indice(tmp_path / "dados" / "i.sqlite")
    teste = tmp_path / "pasta_teste"
    teste.mkdir(exist_ok=True)
    return indice, Quarentena(indice, limite=(teste, perfil), local=lambda arq: perfil / "_quarentena", caches=True)


def test_cache_liberado_so_dentro_da_lista(perfil):
    local = perfil / "AppData" / "Local"
    assert cache_liberado(local / "Temp" / "x.tmp") == "temp"
    assert cache_liberado(local / "Temp") is None  # a pasta em si nunca
    assert cache_liberado(local / "Google" / "Chrome" / "User Data" / "Profile 1" / "Cache" / "a") == "chrome"
    assert cache_liberado(local / "Google" / "Chrome" / "User Data" / "Default" / "Login Data") is None
    assert cache_liberado(local / "Discord" / "settings.json") is None
    assert cache_liberado(Path("C:\\Outro\\AppData\\Local\\Temp\\x")) is None


def test_medir_temp_por_bloco_e_navegador_aberto(perfil):
    achados = {a.limpeza.id: a for a in limpezas.medir(perfil=perfil, abertos=lambda: {"chrome.exe"}, agora=AGORA)}
    temp = achados["temp"]
    nomes = sorted(p.name for p in temp.arquivos)
    assert nomes == ["a.bin", "velho.tmp"]  # novo.tmp fica; sessao_aberta fica INTEIRA
    assert temp.bytes == 3000 and temp.recentes == 3 and temp.motivo is None
    chrome = achados["chrome"]
    assert {p.name for p in chrome.arquivos} == {"f_1", "x"} and chrome.bytes == 4500
    assert len(chrome.pastas) == 2 and "chrome.exe está aberto" in chrome.motivo
    assert achados["npm"].bytes == 600
    assert achados["firefox"].motivo == "nada para limpar"


def test_limpar_vai_para_a_quarentena_e_desfaz(tmp_path, perfil):
    indice, q = _q(tmp_path, perfil)
    with indice:
        achados = [a for a in limpezas.medir(["temp", "chrome", "npm"], perfil=perfil, abertos=set, agora=AGORA)]
        plano = limpezas.planejar(q, achados, abertos=set)
        assert [(p.origem.name, p.problema) for p in plano.passos if p.problema] == []
        assert len(plano.validos) == 5 and plano.total_bytes == 3000 + 4500 + 600
        assert any("esvaziar" in a for a in plano.avisos)
        r = q.executar(plano)
        assert len(r.feitos) == 5 and not r.falhas
        local = perfil / "AppData" / "Local"
        assert not (local / "Temp" / "velho.tmp").exists()
        assert (local / "Temp" / "sessao_aberta" / "antigo.log").exists()  # pasta em uso ficou inteira
        assert (local / "Google" / "Chrome" / "User Data" / "Default" / "Cache").is_dir()  # pastas ficam
        assert (local / "Google" / "Chrome" / "User Data" / "Default" / "Login Data").exists()
        volta = q.planejar_desfazer(lote=r.lote_id)
        assert len(q.executar(volta).feitos) == 5
        assert (local / "Temp" / "velho.tmp").exists() and (local / "npm-cache" / "_cacache" / "index").exists()


def test_resto_do_appdata_continua_proibido(tmp_path, perfil):
    indice, q = _q(tmp_path, perfil)
    with indice:
        plano = q.planejar_mover([perfil / "AppData" / "Local" / "Discord" / "settings.json",
                                  perfil / "AppData" / "Local" / "Google" / "Chrome" / "User Data" / "Default" / "Login Data"])
        assert not plano.validos
        assert all("bloqueada" in p.problema for p in plano.passos)


def test_fora_das_limpezas_o_cache_continua_bloqueado(tmp_path, perfil):
    """O Explorador (ou qualquer outra tela) nunca ganha a exceção: só as Limpezas pedem caches=True."""
    indice = Indice(tmp_path / "dados" / "i.sqlite")
    with indice:
        q = Quarentena(indice, limite=(tmp_path / "pasta_teste", perfil), local=lambda arq: perfil / "_quarentena")
        plano = q.planejar_mover([perfil / "AppData" / "Local" / "Temp" / "velho.tmp"])
        assert not plano.validos and "bloqueada" in plano.passos[0].problema


def test_sem_modo_pc_real_nada_muda(tmp_path, perfil):
    indice = Indice(tmp_path / "dados" / "i.sqlite")
    teste = tmp_path / "pasta_teste"
    teste.mkdir()
    with indice:
        q = Quarentena(indice, limite=teste, local=lambda arq: perfil / "_quarentena", caches=True)  # só a pasta_teste
        plano = limpezas.planejar(q, limpezas.medir(["temp"], perfil=perfil, abertos=set, agora=AGORA), abertos=set)
        assert not plano.validos and all("modo PC real" in p.problema for p in plano.passos)


def test_navegador_que_abriu_depois_da_medicao_fica_de_fora(tmp_path, perfil):
    indice, q = _q(tmp_path, perfil)
    with indice:
        achados = limpezas.medir(["chrome", "npm"], perfil=perfil, abertos=set, agora=AGORA)
        plano = limpezas.planejar(q, achados, abertos=lambda: {"chrome.exe"})
        assert [p.origem.name for p in plano.validos] == ["index"]
        assert any("chrome.exe" in motivo for _, motivo in plano.ignorados)


def test_todas_as_limpezas_tem_pastas_na_lista():
    assert set(limpezas.POR_ID) == set(config.CACHES_LIBERADOS)
    for padroes in config.CACHES_LIBERADOS.values():
        assert all(p.startswith("AppData\\Local\\") for p in padroes)
