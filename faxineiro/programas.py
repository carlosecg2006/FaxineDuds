"""Fase 7C.2 — Programas e jogos instalados: tamanho, data de instalação e último sinal de uso.

SÓ LÊ: o registro do Windows (lista de "Aplicativos instalados" e o histórico do Menu Iniciar),
os manifestos da Steam e as instâncias do CurseForge. O tamanho vem do próprio programa
(registro/Steam) ou da listagem da pasta dele.

"Desinstalar" NUNCA apaga nada por conta própria: chama o desinstalador OFICIAL do programa
(o mesmo das Configurações do Windows), que pede administrador se precisar. Na Steam, abre a
Steam pedindo a desinstalação. CurseForge: só o app dele remove instâncias.
"""

from __future__ import annotations

import codecs
import json
import os
import re
import struct
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .espaco import tamanho_da_pasta

WINDOWS, STEAM, CURSEFORGE = "Windows", "Steam", "CurseForge"
CHAVE_UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
CHAVE_UNINSTALL_32 = r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
CHAVE_USERASSIST = r"Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist"
CONFIGURACOES_APPS = "ms-settings:appsfeatures"  # Configurações > Aplicativos (apps da Loja)

# Pastas conhecidas que o Windows grava como código no histórico do Menu Iniciar.
PASTAS_CONHECIDAS = {
    "{6d809377-6af0-444b-8957-a3773f02200e}": "ProgramFiles",  # Program Files
    "{7c5a40ef-a0fb-4bfc-874a-c0f2e0b9fa8e}": "ProgramFiles(x86)",
    "{f38bf404-1d43-42f2-9305-67de0b28fc23}": "SystemRoot",  # Windows
    "{1ac14e77-02e7-4e5d-b744-2eb1ae5198b7}": "__system32",
    "{d65231b0-b2f1-4857-a4ce-a8e7c6ea7d27}": "__syswow64",
}


@dataclass
class Programa:
    nome: str
    origem: str = WINDOWS  # Windows, Steam ou CurseForge
    editora: str = ""
    versao: str = ""
    tamanho: int | None = None
    instalado_em: str | None = None  # AAAA-MM-DD
    ultimo_uso: str | None = None  # AAAA-MM-DD (histórico do Menu Iniciar / Steam / CurseForge)
    pasta_mudou: str | None = None  # AAAA-MM-DD: arquivo mais novo na pasta (atualização OU uso)
    pasta: str | None = None
    pasta_existe: bool = True
    desinstalador: str | None = None  # linha de comando oficial, ou steam://uninstall/<id>
    como: str = ""  # quando não há desinstalador (CurseForge): o que fazer

    @property
    def sinal_de_uso(self) -> tuple[str | None, str]:
        """O sinal mais confiável de uso, com a fonte (para a tela dizer de onde veio)."""
        if self.ultimo_uso:
            return self.ultimo_uso, "aberto"
        if self.pasta_mudou:
            return self.pasta_mudou, "pasta mudou"
        return None, ""


# --- Windows: "Aplicativos instalados" ---------------------------------------------------------


def ler_registro_uninstall() -> Iterator[dict]:  # pragma: no cover - lê o registro real
    """As entradas do registro (máquina 64/32 bits e usuário). Só lê."""
    import winreg

    for raiz, sub in ((winreg.HKEY_LOCAL_MACHINE, CHAVE_UNINSTALL), (winreg.HKEY_LOCAL_MACHINE, CHAVE_UNINSTALL_32),
                      (winreg.HKEY_CURRENT_USER, CHAVE_UNINSTALL)):
        try:
            chave = winreg.OpenKey(raiz, sub)
        except OSError:
            continue
        with chave:
            for i in range(winreg.QueryInfoKey(chave)[0]):
                try:
                    nome = winreg.EnumKey(chave, i)
                    with winreg.OpenKey(chave, nome) as s:
                        valores = {}
                        for j in range(winreg.QueryInfoKey(s)[1]):
                            n, v, _ = winreg.EnumValue(s, j)
                            valores[n] = v
                except OSError:
                    continue
                valores["_chave"] = nome
                yield valores


def separar_comando(linha: str) -> tuple[str, str]:
    """'"C:\\X\\unins.exe" /S' → ('C:\\X\\unins.exe', '/S'). Aceita caminho sem aspas e com espaços."""
    linha = linha.strip()
    if linha.startswith('"'):
        fim = linha.find('"', 1)
        if fim > 0:
            return linha[1:fim], linha[fim + 1:].strip()
    m = re.search(r"\.exe\b", linha, re.IGNORECASE)
    if m:
        return linha[:m.end()], linha[m.end():].strip()
    exe, _, args = linha.partition(" ")
    return exe, args.strip()


def _pasta_do_exe(texto: str | None) -> str | None:
    """Pasta do .exe de um ícone ('C:\\X\\app.exe,0') ou de um desinstalador. Nunca msiexec/Windows."""
    if not texto:
        return None
    exe = separar_comando(texto.split(",")[0] if texto.count('"') == 0 else texto)[0]
    if not exe.lower().endswith(".exe") or not Path(exe).is_absolute():
        return None
    pasta = Path(exe).parent
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    if pasta == windows or windows in pasta.parents and pasta.name.casefold() in ("system32", "syswow64"):
        return None
    texto_pasta = str(pasta).casefold()
    if any(f"\\{nome}\\" in texto_pasta + "\\" for nome in PASTAS_DE_INSTALADORES):
        return None  # o desinstalador mora lá, mas o programa não
    return str(pasta)


# Instaladores guardados e peças compartilhadas: o desinstalador mora lá, mas o programa não
# (ex.: o do Office fica em Common Files\Microsoft Shared\ClickToRun).
PASTAS_DE_INSTALADORES = ("package cache", "installshield installation information", "installer", "common files")
# App web instalado pelo Chrome/Edge ("Instalar página como app"): o desinstalador é o navegador.
APP_WEB = re.compile(r"--uninstall-app-id|--app-id", re.IGNORECASE)


def _data_registro(texto) -> str | None:
    texto = str(texto or "")
    if re.fullmatch(r"\d{8}", texto):
        try:
            return datetime.strptime(texto, "%Y%m%d").date().isoformat()
        except ValueError:
            return None
    return None


IGNORAR_TIPOS = {"update", "hotfix", "security update", "service pack"}


def do_registro(entradas: Iterable[dict]) -> list[Programa]:
    """Transforma as entradas do registro em programas: sem componentes do sistema, sem
    atualizações (KB...), sem repetidos (o mesmo programa nas chaves de 32 e 64 bits)."""
    vistos: set[tuple[str, str]] = set()
    programas = []
    for v in entradas:
        nome = str(v.get("DisplayName") or "").strip()
        if (not nome or v.get("SystemComponent") == 1 or v.get("ParentKeyName")
                or str(v.get("ReleaseType", "")).casefold() in IGNORAR_TIPOS or re.match(r"^KB\d+", nome)):
            continue
        desinstalador = v.get("QuietUninstallString") if not v.get("UninstallString") else v.get("UninstallString")
        if not desinstalador:
            continue  # sem desinstalador oficial, o Windows também não lista
        versao = str(v.get("DisplayVersion") or "")
        if (nome.casefold(), versao) in vistos:
            continue
        vistos.add((nome.casefold(), versao))
        local = str(v.get("InstallLocation") or "").strip().strip('"').rstrip("\\") or None
        if APP_WEB.search(str(desinstalador)):
            pasta = None  # app web: ocupa quase nada; a pasta do navegador não é dele
        else:
            pasta = local or _pasta_do_exe(v.get("DisplayIcon")) or _pasta_do_exe(desinstalador)
        tamanho = v.get("EstimatedSize")
        steam = re.search(r"steam://uninstall/\d+", str(desinstalador))
        programas.append(Programa(
            nome=nome, origem=STEAM if steam else WINDOWS, editora=str(v.get("Publisher") or ""), versao=versao,
            tamanho=int(tamanho) * 1024 if isinstance(tamanho, int) and tamanho > 0 else None,
            instalado_em=_data_registro(v.get("InstallDate")), pasta=pasta,
            desinstalador=steam.group(0) if steam else str(desinstalador)))
    return programas


# --- Steam ---------------------------------------------------------------------------------------


def _vdf(texto: str) -> dict[str, str]:
    """Pares "chave" "valor" de um arquivo da Steam (.acf/.vdf), sem a hierarquia (basta aqui)."""
    return {k.casefold(): v.replace("\\\\", "\\") for k, v in re.findall(r'"([^"]+)"\s+"([^"]*)"', texto)}


def bibliotecas_steam(pasta_steam: Path) -> list[Path]:
    """As pastas 'steamapps' de todas as bibliotecas (a principal + as de libraryfolders.vdf)."""
    pastas = [pasta_steam / "steamapps"]
    try:
        texto = (pasta_steam / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
        pastas += [Path(p.replace("\\\\", "\\")) / "steamapps" for p in re.findall(r'"path"\s+"([^"]+)"', texto)]
    except OSError:
        pass
    unicas = []
    for p in pastas:
        if os.path.normcase(str(p)) not in {os.path.normcase(str(u)) for u in unicas}:
            unicas.append(p)
    return unicas


def _dia(timestamp: str | int | float | None) -> str | None:
    try:
        t = int(timestamp or 0)
    except ValueError:
        return None
    return datetime.fromtimestamp(t).date().isoformat() if t > 0 else None


def da_steam(bibliotecas: Iterable[Path]) -> list[Programa]:
    """Um jogo por appmanifest_*.acf (nome, tamanho, último uso e o id para desinstalar)."""
    jogos = []
    for steamapps in bibliotecas:
        try:
            manifestos = sorted(steamapps.glob("appmanifest_*.acf"))
        except OSError:
            continue
        for acf in manifestos:
            try:
                d = _vdf(acf.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if "appid" not in d or "name" not in d:
                continue
            pasta = steamapps / "common" / d.get("installdir", "")
            jogos.append(Programa(
                nome=d["name"], origem=STEAM, editora="Steam",
                tamanho=int(d["sizeondisk"]) if d.get("sizeondisk", "").isdigit() else None,
                ultimo_uso=_dia(d.get("lastplayed")), instalado_em=None, pasta=str(pasta),
                desinstalador=f"steam://uninstall/{d['appid']}"))
    return jogos


def pasta_da_steam() -> Path | None:  # pragma: no cover - lê o registro real
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            return Path(winreg.QueryValueEx(k, "SteamPath")[0])
    except OSError:
        return None


# --- CurseForge (Minecraft) ------------------------------------------------------------------------

PASTA_CURSEFORGE = config.PASTA_DO_USUARIO / "curseforge" / "minecraft" / "Instances"


def do_curseforge(instancias: Path = PASTA_CURSEFORGE) -> list[Programa]:
    """Cada instância (modpack) do CurseForge vira uma linha: o tamanho conta mods, mundos e saves."""
    achadas = []
    try:
        pastas = sorted(p for p in instancias.iterdir() if p.is_dir())
    except OSError:
        return achadas
    for pasta in pastas:
        info: dict = {}
        try:
            info = json.loads((pasta / "minecraftinstance.json").read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            pass
        ultimo = str(info.get("lastPlayed") or "")[:10] or None
        if ultimo and ultimo.startswith("0001"):
            ultimo = None  # nunca jogado
        achadas.append(Programa(
            nome=f"Minecraft — {info.get('name') or pasta.name}", origem=CURSEFORGE, editora="CurseForge",
            ultimo_uso=ultimo, pasta=str(pasta),
            como="Remova pelo app do CurseForge (Minha biblioteca → ⋮ → Excluir): ele cuida dos mundos e saves."))
    return achadas


# --- histórico de uso do Menu Iniciar (UserAssist) -------------------------------------------------


def _filetime(dado: bytes) -> str | None:
    """Os 72 bytes de cada item: a data da última vez que foi aberto fica no byte 60."""
    if len(dado) < 68:
        return None
    ft = struct.unpack_from("<Q", dado, 60)[0]
    if ft <= 0:
        return None
    try:
        return datetime.fromtimestamp((ft - 116444736000000000) / 1e7, tz=timezone.utc).astimezone().date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _expandir(caminho: str) -> str:
    cabeca, sep, resto = caminho.partition("\\")
    pasta = PASTAS_CONHECIDAS.get(cabeca.casefold())
    if pasta is None:
        return caminho
    raiz = os.environ.get("SystemRoot", r"C:\Windows")
    base = {"__system32": os.path.join(raiz, "System32"), "__syswow64": os.path.join(raiz, "SysWOW64")}.get(
        pasta, os.environ.get(pasta, ""))
    return os.path.join(base, resto) if base else caminho


def ler_userassist() -> dict[str, str]:  # pragma: no cover - lê o registro real
    """{caminho do .exe (minúsculo): AAAA-MM-DD da última abertura}. Os nomes vêm em ROT13."""
    if sys.platform != "win32":
        return {}
    import winreg

    usos: dict[str, str] = {}
    try:
        raiz = winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_USERASSIST)
    except OSError:
        return usos
    with raiz:
        for i in range(winreg.QueryInfoKey(raiz)[0]):
            try:
                contagem = winreg.OpenKey(raiz, winreg.EnumKey(raiz, i) + r"\Count")
            except OSError:
                continue
            with contagem:
                for j in range(winreg.QueryInfoKey(contagem)[1]):
                    nome, dado, _ = winreg.EnumValue(contagem, j)
                    if isinstance(dado, bytes) and (dia := _filetime(dado)):
                        caminho = os.path.normcase(_expandir(codecs.decode(nome, "rot13")))
                        usos[caminho] = max(dia, usos.get(caminho, ""))
    return usos


def aplicar_usos(programas: list[Programa], usos: dict[str, str]) -> None:
    """Último uso = a abertura mais recente de qualquer .exe dentro da pasta do programa."""
    for p in programas:
        if not p.pasta or p.origem == CURSEFORGE:
            continue
        base = os.path.normcase(p.pasta.rstrip("\\")) + "\\"
        dias = [d for caminho, d in usos.items() if caminho.startswith(base)]
        if dias:
            p.ultimo_uso = max(filter(None, [p.ultimo_uso, *dias]))


# --- pasta: existe? tamanho e arquivo mais novo -------------------------------------------------------


def _mais_novo(pasta: str) -> str | None:
    """Data do arquivo mais novo na pasta e um nível abaixo (rápido; atualização também conta)."""
    maior = 0.0
    for alvo in (pasta, *(e.path for e in _entradas(pasta) if e.is_dir(follow_symlinks=False))):
        for e in _entradas(alvo):
            try:
                if e.is_file(follow_symlinks=False):
                    maior = max(maior, e.stat(follow_symlinks=False).st_mtime)
            except OSError:
                pass
    return datetime.fromtimestamp(maior).date().isoformat() if maior else None


def _entradas(pasta: str) -> list[os.DirEntry]:
    try:
        with os.scandir(pasta) as it:
            return list(it)
    except OSError:
        return []


def completar_pastas(programas: list[Programa], parar: Callable[[], bool] = lambda: False,
                     ao_progredir: Callable[[int, int, str], None] | None = None) -> None:
    """Confere se a pasta existe (unidade E: desconectada...), mede quem não disse o tamanho e
    acha a data do arquivo mais novo. Só pela listagem."""
    for n, p in enumerate(programas):
        if parar():
            return
        if ao_progredir:
            ao_progredir(n, len(programas), p.nome)
        if not p.pasta:
            continue
        p.pasta_existe = os.path.isdir(p.pasta)
        if not p.pasta_existe:
            continue
        pasta = Path(p.pasta)
        if p.tamanho is None and pasta != Path(pasta.anchor):
            p.tamanho = tamanho_da_pasta(pasta)
        p.pasta_mudou = _mais_novo(p.pasta)


def listar(
    *,
    registro: Callable[[], Iterable[dict]] = ler_registro_uninstall,
    steam: Callable[[], Path | None] = pasta_da_steam,
    curseforge: Path = PASTA_CURSEFORGE,
    usos: Callable[[], dict[str, str]] = ler_userassist,
    parar: Callable[[], bool] = lambda: False,
    ao_progredir: Callable[[int, int, str], None] | None = None,
) -> list[Programa]:
    """Todos os programas e jogos, do maior para o menor (sem tamanho conhecido vão para o fim)."""
    programas = do_registro(registro())
    pasta_steam = steam()
    if pasta_steam is not None:
        ja = {p.desinstalador for p in programas if p.origem == STEAM}
        programas += [j for j in da_steam(bibliotecas_steam(pasta_steam)) if j.desinstalador not in ja]
    programas += do_curseforge(curseforge)
    aplicar_usos(programas, usos())
    completar_pastas(programas, parar, ao_progredir)
    programas.sort(key=lambda p: (p.tamanho is None, -(p.tamanho or 0), p.nome.casefold()))
    return programas


# --- desinstalar: SEMPRE o desinstalador oficial ------------------------------------------------------


def _shell(arquivo: str, argumentos: str) -> None:  # pragma: no cover - abre programas de verdade
    """ShellExecute "open": se o desinstalador pede administrador, o Windows mostra o UAC."""
    import ctypes

    codigo = ctypes.windll.shell32.ShellExecuteW(None, "open", arquivo, argumentos or None, None, 1)
    if codigo <= 32:
        raise OSError(f"o Windows não conseguiu abrir o desinstalador (código {codigo})")


def desinstalar(programa: Programa, abrir: Callable[[str, str], None] = _shell) -> str:
    """Abre o desinstalador oficial. Não espera ele terminar: o usuário segue as telas dele.
    Devolve o que foi chamado (para mostrar). Os testes passam um `abrir` falso."""
    if not programa.desinstalador:
        raise ValueError(programa.como or "Este programa não tem desinstalador registrado.")
    if programa.desinstalador.startswith("steam://"):
        abrir(programa.desinstalador, "")
        return programa.desinstalador
    arquivo, argumentos = separar_comando(programa.desinstalador)
    abrir(arquivo, argumentos)
    return f"{arquivo} {argumentos}".strip()


def abrir_aplicativos_da_loja(abrir: Callable[[str, str], None] = _shell) -> None:
    """Apps da Microsoft Store: quem desinstala é o Windows (Configurações > Aplicativos)."""
    abrir(CONFIGURACOES_APPS, "")
