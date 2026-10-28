"""Fase 7C.2 — Programas e jogos. Registro, Steam e CurseForge falsos; nenhum desinstalador de verdade abre."""

import json
import os
import struct
from datetime import datetime
from pathlib import Path

import pytest

from faxineiro import programas
from faxineiro.programas import Programa


def _criar(caminho: Path, tamanho: int = 10) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(b"x" * tamanho)
    return caminho


# --- registro ---------------------------------------------------------------------------------


def test_registro_filtra_componentes_atualizacoes_e_repetidos():
    entradas = [
        {"DisplayName": "Git", "DisplayVersion": "2.5", "EstimatedSize": 1000, "InstallDate": "20260704",
         "InstallLocation": "C:\\Program Files\\Git\\", "UninstallString": '"C:\\Program Files\\Git\\unins000.exe"'},
        {"DisplayName": "Git", "DisplayVersion": "2.5", "UninstallString": "x.exe"},  # mesma (chave 32 bits)
        {"DisplayName": "Peça do sistema", "SystemComponent": 1, "UninstallString": "y.exe"},
        {"DisplayName": "Atualização", "ParentKeyName": "Office", "UninstallString": "z.exe"},
        {"DisplayName": "KB5001234", "UninstallString": "w.exe"},
        {"DisplayName": "Sem desinstalador"},
        {"UninstallString": "sem_nome.exe"},
    ]
    ps = programas.do_registro(entradas)
    assert [p.nome for p in ps] == ["Git"]
    git = ps[0]
    assert git.tamanho == 1000 * 1024 and git.instalado_em == "2026-07-04"
    assert git.pasta == "C:\\Program Files\\Git" and git.origem == programas.WINDOWS


def test_registro_deduz_a_pasta_mas_nao_a_dos_instaladores():
    ps = programas.do_registro([
        {"DisplayName": "Discord", "DisplayIcon": "C:\\Users\\c\\AppData\\Local\\Discord\\app.ico.exe,0",
         "UninstallString": "C:\\Users\\c\\AppData\\Local\\Discord\\Update.exe --uninstall"},
        {"DisplayName": "Runtime", "UninstallString": '"C:\\ProgramData\\Package Cache\\{abc}\\setup.exe" /u'},
        {"DisplayName": "Office", "UninstallString":
         '"C:\\Program Files\\Common Files\\Microsoft Shared\\ClickToRun\\OfficeClickToRun.exe" scenario=install'},
        {"DisplayName": "MSI", "UninstallString": "MsiExec.exe /X{1D8E6291}"},
        {"DisplayName": "Instagram", "DisplayIcon": "C:\\Program Files\\Google\\Chrome\\chrome.exe,0",
         "UninstallString": '"C:\\Program Files\\Google\\Chrome\\chrome_proxy.exe" --uninstall-app-id=abc'},
    ])
    pastas = {p.nome: p.pasta for p in ps}
    assert pastas == {"Discord": "C:\\Users\\c\\AppData\\Local\\Discord", "Runtime": None, "Office": None,
                      "MSI": None, "Instagram": None}


def test_jogo_steam_no_registro_vira_origem_steam():
    p = programas.do_registro([{"DisplayName": "Westland", "UninstallString": '"E:\\Steam\\steam.exe" steam://uninstall/2730970'}])[0]
    assert p.origem == programas.STEAM and p.desinstalador == "steam://uninstall/2730970"


@pytest.mark.parametrize("linha, esperado", [
    ('"C:\\Program Files\\Git\\unins000.exe" /SILENT', ("C:\\Program Files\\Git\\unins000.exe", "/SILENT")),
    ("C:\\Program Files\\McAfee\\WebAdvisor\\Uninstaller.exe /x", ("C:\\Program Files\\McAfee\\WebAdvisor\\Uninstaller.exe", "/x")),
    ("MsiExec.exe /X{1D8E6291-B0D5}", ("MsiExec.exe", "/X{1D8E6291-B0D5}")),
    ("E:\\WinRAR\\uninstall.exe", ("E:\\WinRAR\\uninstall.exe", "")),
])
def test_separar_comando(linha, esperado):
    assert programas.separar_comando(linha) == esperado


# --- Steam e CurseForge ----------------------------------------------------------------------------


def test_steam_le_bibliotecas_e_manifestos(tmp_path):
    steam, outra = tmp_path / "Steam", tmp_path / "Jogos"
    _criar(steam / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n "0" { "path" "%s" }\n "1" { "path" "%s" }\n}' % (
            str(steam).replace("\\", "\\\\"), str(outra).replace("\\", "\\\\")), encoding="utf-8")
    jogou = int(datetime(2026, 9, 1, 12).timestamp())
    _criar(outra / "steamapps" / "appmanifest_570.acf").write_text(
        f'"AppState"\n{{\n "appid" "570"\n "name" "Dota 2"\n "installdir" "dota 2 beta"\n'
        f' "SizeOnDisk" "40000000000"\n "LastPlayed" "{jogou}"\n}}', encoding="utf-8")
    bibliotecas = programas.bibliotecas_steam(steam)
    assert len(bibliotecas) == 2
    jogos = programas.da_steam(bibliotecas)
    assert len(jogos) == 1
    dota = jogos[0]
    assert (dota.nome, dota.tamanho, dota.ultimo_uso) == ("Dota 2", 40_000_000_000, "2026-09-01")
    assert dota.desinstalador == "steam://uninstall/570"
    assert dota.pasta == str(outra / "steamapps" / "common" / "dota 2 beta")


def test_curseforge_instancias(tmp_path):
    inst = tmp_path / "Instances"
    _criar(inst / "Story" / "mods" / "a.jar", 500)
    (inst / "Story" / "minecraftinstance.json").write_text(
        json.dumps({"name": "Story Mode", "lastPlayed": "2026-03-01T10:00:00Z"}), encoding="utf-8")
    _criar(inst / "vanilla" / "x.dat", 50)
    ps = programas.do_curseforge(inst)
    assert [p.nome for p in ps] == ["Minecraft — Story Mode", "Minecraft — vanilla"]
    assert ps[0].ultimo_uso == "2026-03-01" and ps[0].desinstalador is None and "CurseForge" in ps[0].como
    with pytest.raises(ValueError, match="CurseForge"):
        programas.desinstalar(ps[0], abrir=lambda *a: pytest.fail("não pode abrir nada"))


# --- uso e pastas -------------------------------------------------------------------------------------


def test_filetime_do_userassist():
    ft = int((datetime(2026, 10, 27, 15).timestamp()) * 1e7) + 116444736000000000
    dado = bytearray(72)
    struct.pack_into("<Q", dado, 60, ft)
    assert programas._filetime(bytes(dado)) == "2026-10-27"
    assert programas._filetime(bytes(72)) is None and programas._filetime(b"curto") is None


def test_aplicar_usos_pela_pasta_do_programa():
    fl = Programa("FL Studio", pasta="C:\\Program Files (x86)\\Image-Line\\FL Studio 20")
    outro = Programa("Outro", pasta="C:\\Program Files (x86)\\Image-Line\\FL Studio 2")  # prefixo parecido
    usos = {os.path.normcase("C:\\Program Files (x86)\\Image-Line\\FL Studio 20\\FL64.exe"): "2026-10-27",
            os.path.normcase("C:\\Program Files (x86)\\Image-Line\\FL Studio 20\\FL.exe"): "2026-01-01"}
    programas.aplicar_usos([fl, outro], usos)
    assert fl.ultimo_uso == "2026-10-27" and outro.ultimo_uso is None
    assert fl.sinal_de_uso == ("2026-10-27", "aberto")


def test_expandir_pasta_conhecida(monkeypatch):
    monkeypatch.setenv("ProgramFiles", "C:\\Program Files")
    assert programas._expandir("{6D809377-6AF0-444B-8957-A3773F02200E}\\Git\\git.exe") == "C:\\Program Files\\Git\\git.exe"
    assert programas._expandir("C:\\x\\y.exe") == "C:\\x\\y.exe"


def test_completar_pastas_mede_e_marca_sumidas(tmp_path):
    _criar(tmp_path / "App" / "app.exe", 3000)
    _criar(tmp_path / "App" / "dados" / "d.bin", 1000)
    medido = Programa("App", pasta=str(tmp_path / "App"))
    informado = Programa("Info", pasta=str(tmp_path / "App"), tamanho=7)
    sumido = Programa("Sumido", pasta=str(tmp_path / "E_desconectado" / "App"))
    programas.completar_pastas([medido, informado, sumido])
    assert medido.tamanho == 4000 and medido.pasta_mudou is not None
    assert informado.tamanho == 7  # o tamanho do registro vale
    assert not sumido.pasta_existe and sumido.tamanho is None
    assert medido.sinal_de_uso[1] == "pasta mudou"


def test_listar_junta_tudo_sem_repetir_steam(tmp_path):
    steam = tmp_path / "Steam"
    _criar(steam / "steamapps" / "appmanifest_1.acf").write_text(
        '"AppState" { "appid" "1" "name" "Jogo" "SizeOnDisk" "500" }', encoding="utf-8")
    _criar(steam / "steamapps" / "appmanifest_2.acf").write_text(
        '"AppState" { "appid" "2" "name" "Outro" "SizeOnDisk" "900" }', encoding="utf-8")
    registro = [{"DisplayName": "Jogo", "UninstallString": "steam.exe steam://uninstall/1"},
                {"DisplayName": "Editor", "EstimatedSize": 2, "UninstallString": "MsiExec.exe /X{A}"}]
    ps = programas.listar(registro=lambda: registro, steam=lambda: steam, curseforge=tmp_path / "nada",
                          usos=lambda: {})
    assert [p.nome for p in ps] == ["Editor", "Outro", "Jogo"]  # Jogo só uma vez (sem tamanho → fim)


# --- desinstalar: só abre o oficial --------------------------------------------------------------------


def test_desinstalar_abre_o_desinstalador_oficial():
    chamadas = []
    p = Programa("Git", desinstalador='"C:\\Program Files\\Git\\unins000.exe" /SILENT')
    assert programas.desinstalar(p, abrir=lambda a, b: chamadas.append((a, b)))
    assert chamadas == [("C:\\Program Files\\Git\\unins000.exe", "/SILENT")]
    chamadas.clear()
    programas.desinstalar(Programa("Dota", desinstalador="steam://uninstall/570"), abrir=lambda a, b: chamadas.append((a, b)))
    assert chamadas == [("steam://uninstall/570", "")]
    chamadas.clear()
    programas.abrir_aplicativos_da_loja(lambda a, b: chamadas.append(a))
    assert chamadas == ["ms-settings:appsfeatures"]
