"""Fase 7C.1 — Raio-X do sistema. A "unidade" é uma pasta do tmp_path com Windows, Program Files e AppData falsos."""

import os
from pathlib import Path

import pytest

from faxineiro import espaco, sistema
from faxineiro.cli_sistema import mostrar


def _criar(caminho: Path, tamanho: int) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(b"x" * tamanho)


@pytest.fixture
def unidade(tmp_path):
    raiz = tmp_path / "C"
    perfil = raiz / "Users" / "Carlos"
    _criar(raiz / "Windows" / "System32" / "kernel.dll", 3000)
    _criar(raiz / "Windows" / "WinSxS" / "comp" / "a.dll", 2000)
    _criar(raiz / "Windows" / "Temp" / "lixo.tmp", 500)
    _criar(raiz / "Windows" / "Cursores" / "x.cur", 10)  # pequena e desconhecida: some
    _criar(raiz / "Program Files" / "Jogo" / "jogo.exe", 4000)
    _criar(raiz / "Program Files" / "Common Files" / "c.dll", 100)
    _criar(raiz / "ProgramData" / "AppX" / "dados.bin", 700)
    _criar(raiz / "pagefile.sys", 900)
    _criar(raiz / "Documentos" / "trabalho.docx", 5000)  # pasta do usuário: fora do Raio-X do sistema
    _criar(perfil / "AppData" / "Local" / "Temp" / "a.tmp", 300)
    _criar(perfil / "AppData" / "Local" / "Google" / "Chrome" / "User Data" / "Default" / "Cache" / "f_1", 1200)
    _criar(perfil / "AppData" / "Roaming" / "Discord" / "settings.json", 800)
    _criar(perfil / "Documents" / "nota.txt", 50)
    return raiz, perfil


def _medir(unidade, **kw):
    raiz, perfil = unidade
    return sistema.medir_sistema(raiz, perfil=perfil, minimo=kw.pop("minimo", 200), uso=lambda r: (10**9, 10**6, 0), **kw)


def _achar(itens, nome):
    for i in itens:
        if i.nome.casefold() == nome.casefold():
            return i
        if (achado := _achar(i.filhos, nome)) is not None:
            return achado
    return None


def test_mede_so_as_pastas_de_sistema(unidade):
    rx = _medir(unidade)
    nomes = {i.nome for i in rx.itens}
    assert nomes == {"Windows", "Program Files", "ProgramData", "AppData", "pagefile.sys"}
    assert _achar(rx.itens, "Documentos") is None and _achar(rx.itens, "Documents") is None
    assert _achar(rx.itens, "Windows").tamanho == 3000 + 2000 + 500 + 10
    assert rx.total == 5510 + 4100 + 700 + 2300 + 900
    assert not rx.cancelado


def test_selos_e_explicacoes(unidade):
    rx = _medir(unidade)
    assert _achar(rx.itens, "WinSxS").selo == sistema.NAO_MEXA
    assert "links" in _achar(rx.itens, "WinSxS").explicacao
    temp_windows = _achar(rx.itens, "Windows").filhos
    assert next(f for f in temp_windows if f.nome == "Temp").selo == sistema.SEGURO
    jogo = _achar(rx.itens, "Jogo")
    assert jogo.selo == sistema.DESINSTALADOR and "Jogo" in jogo.explicacao
    assert _achar(rx.itens, "Common Files").selo == sistema.NAO_MEXA  # conhecida (pequena, mas aparece)
    discord = _achar(rx.itens, "Discord")
    assert discord.selo == sistema.NAO_MEXA and "Discord" in discord.explicacao
    assert _achar(rx.itens, "pagefile.sys").arquivo


def test_ajustes_da_medicao_real(unidade):
    """Windows Kits desinstala; Edge/WebView2 é parte do Windows; WinSxS só mostra o total."""
    raiz, _ = unidade
    _criar(raiz / "Program Files (x86)" / "Windows Kits" / "10" / "sdk.lib", 600)
    _criar(raiz / "Program Files (x86)" / "Microsoft" / "EdgeWebView" / "w.dll", 600)
    _criar(raiz / "Windows" / "WinSxS" / "amd64_algo_31bf3856ad364e35" / "x.dll", 900)
    rx = _medir(unidade)
    assert _achar(rx.itens, "Windows Kits").selo == sistema.DESINSTALADOR
    assert _achar(rx.itens, "EdgeWebView").selo == sistema.NAO_MEXA
    winsxs = _achar(rx.itens, "WinSxS")
    assert winsxs.filhos == [] and winsxs.tamanho == 2900


def test_conhecida_funda_aparece_no_ancestral_mais_perto(unidade):
    rx = _medir(unidade)
    google = _achar(rx.itens, "Google")  # AppData(0) → Local(1) → Google(2)
    cache = next(f for f in google.filhos if f.nome == "Cache")
    assert cache.selo == sistema.SEGURO and cache.tamanho == 1200 and "Chrome" in cache.explicacao
    assert sistema.NAVEGADOR in cache.como


def test_pasta_pequena_e_desconhecida_some_mas_conta_no_pai(unidade):
    rx = _medir(unidade)
    assert _achar(rx.itens, "Cursores") is None
    assert _achar(rx.itens, "Windows").tamanho == 5510


def test_nao_segue_juncoes(unidade, tmp_path):
    raiz, perfil = unidade
    alvo = raiz / "Documentos"
    link = raiz / "Windows" / "Atalho"
    try:
        os.symlink(alvo, link, target_is_directory=True)
    except OSError:
        pytest.skip("sem permissão para criar link simbólico neste Windows")
    assert _achar(_medir(unidade).itens, "Windows").tamanho == 5510


def test_nao_mexe_em_nada(unidade):
    raiz, _ = unidade
    antes = sorted((str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in raiz.rglob("*"))
    _medir(unidade)
    assert sorted((str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in raiz.rglob("*")) == antes


def test_cancelar(unidade):
    # só pergunta de 200 em 200 pastas: numa unidade pequena termina antes. Força com muitas pastas:
    raiz, _ = unidade
    for n in range(250):
        (raiz / "Windows" / "muitas" / str(n)).mkdir(parents=True)
    rx = _medir(unidade, parar=lambda: True)
    assert rx.cancelado


def test_salvar_e_carregar(unidade, tmp_path):
    rx = _medir(unidade)
    destino = sistema.arquivo_salvo("C:", tmp_path / "dados")
    assert destino.name == "sistema_C.json"
    sistema.salvar(rx, destino)
    volta = sistema.carregar(destino)
    assert volta == rx
    assert sistema.carregar(tmp_path / "nao_existe.json") is None


def test_arquivos_de_sistema_tem_explicacao():
    assert set(sistema._ARQUIVOS) == set(espaco.ARQUIVOS_DE_SISTEMA)


def test_padroes_comecam_com_raiz_ou_perfil():
    for c in sistema.CONHECIDAS:
        assert c.padrao.split("\\")[0] in ("{raiz}", "{perfil}"), c.padrao
        assert c.selo in (sistema.SEGURO, sistema.DESINSTALADOR, sistema.NAO_MEXA)
        assert c.selo == sistema.NAO_MEXA or c.como, f"{c.padrao}: selo sem 'como'"


def test_cli_mostra_em_portugues(unidade, capsys):
    mostrar(_medir(unidade))
    saida = capsys.readouterr().out
    assert "[seguro limpar]" in saida and "[use o desinstalador]" in saida and "[não mexa]" in saida
    assert "Nada foi movido nem apagado" in saida
