"""Fase 7C.3 — Limpezas seguras: temporários e caches que os programas refazem sozinhos.

A lista é FIXA (`config.CACHES_LIBERADOS`, estudada no BleachBit sem copiar código dele) e tudo
vai para a QUARENTENA, com prévia e desfazer — o espaço só é liberado ao esvaziar.

Cuidados:
- navegador aberto → aquela limpeza fica de fora (ele está usando o cache);
- %TEMP%: o que foi mexido nas últimas 24 h fica; uma subpasta com QUALQUER arquivo recente fica
  inteira (pode ser de um instalador ou de um programa rodando agora);
- arquivo em uso: o Windows não deixa mover, vira "falhou" na hora e nada muda;
- só arquivos: as pastas do cache ficam (os programas esperam encontrá-las).
"""

from __future__ import annotations

import csv
import io
import os
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path

from . import config, disco
from .quarentena import Plano, Quarentena

HORA = 3600


@dataclass(frozen=True)
class Limpeza:
    id: str  # chave em config.CACHES_LIBERADOS
    titulo: str
    explicacao: str
    navegador: str | None = None  # .exe que precisa estar FECHADO
    idade_minima: int = 0  # segundos: arquivos mais novos que isso ficam


LIMPEZAS: tuple[Limpeza, ...] = (
    Limpeza("temp", "Arquivos temporários (%TEMP%)",
            "Arquivos que os programas e instaladores criam para usar uma vez e esquecem. "
            "O que foi mexido nas últimas 24 horas fica — e uma pasta com qualquer arquivo recente "
            "fica inteira (um programa pode estar usando).", idade_minima=24 * HORA),
    Limpeza("chrome", "Cache do Google Chrome",
            "Páginas, imagens e scripts guardados para abrir sites mais rápido. O Chrome baixa de novo "
            "quando precisar. Não mexe em senhas, histórico, cookies nem favoritos.", navegador="chrome.exe"),
    Limpeza("edge", "Cache do Microsoft Edge",
            "Páginas, imagens e scripts guardados para abrir sites mais rápido. O Edge baixa de novo "
            "quando precisar. Não mexe em senhas, histórico, cookies nem favoritos.", navegador="msedge.exe"),
    Limpeza("firefox", "Cache do Firefox",
            "Páginas e imagens guardadas pelo Firefox. Não mexe em senhas, histórico nem favoritos.",
            navegador="firefox.exe"),
    Limpeza("npm", "Cache do npm (Node.js)",
            "Pacotes que o npm já baixou. Se um projeto precisar, ele baixa de novo (mais devagar só na 1ª vez)."),
    Limpeza("pip", "Cache do pip (Python)",
            "Pacotes que o pip já baixou. Se precisar, ele baixa de novo (mais devagar só na 1ª vez)."),
    Limpeza("crashdumps", "Relatórios de travamento (CrashDumps)",
            "Cópias da memória de programas que travaram. Só servem para quem desenvolve o programa."),
)
POR_ID = {lim.id: lim for lim in LIMPEZAS}


@dataclass
class Achado:
    limpeza: Limpeza
    pastas: list[Path] = field(default_factory=list)  # as pastas de cache que existem
    arquivos: list[Path] = field(default_factory=list)
    bytes: int = 0
    recentes: int = 0  # ficaram por serem novos demais
    navegador_aberto: bool = False

    @property
    def motivo(self) -> str | None:
        """Por que esta limpeza não pode ser feita agora (None = pode)."""
        if self.navegador_aberto:
            return f"{self.limpeza.navegador} está aberto: feche o navegador e meça de novo"
        if not self.arquivos:
            return "nada para limpar"
        return None


def pastas_do_cache(chave: str, perfil: Path | None = None) -> list[Path]:
    """As pastas de cache que existem para `chave`, expandindo '*' (perfis do navegador)."""
    perfil = Path(perfil or config.PASTA_DO_USUARIO)
    achadas: list[Path] = []
    for padrao in config.CACHES_LIBERADOS[chave]:
        atuais = [perfil]
        for pedaco in padrao.split("\\"):
            proximas = []
            for base in atuais:
                if "*" in pedaco:
                    proximas += [base / e.name for e in _entradas(base)  # e.path viria com \\?\
                                 if e.is_dir(follow_symlinks=False) and fnmatchcase(e.name.casefold(), pedaco.casefold())]
                elif (base / pedaco).is_dir():
                    proximas.append(base / pedaco)
            atuais = proximas
        achadas += atuais
    return sorted(set(achadas))


def _entradas(pasta: Path) -> list[os.DirEntry]:
    try:
        with os.scandir(disco.no_disco(pasta)) as it:
            return list(it)
    except OSError:
        return []


def _todos(pasta: Path) -> list[tuple[Path, int, float]]:
    """(arquivo, tamanho, data de modificação) de tudo dentro da pasta. Não segue atalhos nem junções."""
    achados, pilha = [], [pasta]
    while pilha:
        atual = pilha.pop()
        for e in _entradas(atual):
            try:
                if e.is_symlink() or getattr(e, "is_junction", lambda: False)():
                    continue
                if e.is_dir(follow_symlinks=False):
                    pilha.append(atual / e.name)
                else:
                    st = e.stat(follow_symlinks=False)
                    achados.append((atual / e.name, st.st_size, st.st_mtime))
            except OSError:
                continue
    return achados


def _arquivos(pasta: Path, idade_minima: int, agora: float) -> tuple[list[Path], int, int]:
    """(arquivos, bytes, recentes) que podem sair da pasta.

    Com `idade_minima` (o %TEMP%), cada SUBPASTA de cima vale como um bloco: se qualquer arquivo
    dela foi mexido há pouco, ela fica inteira — um programa pode estar usando (ex.: a pasta de
    trabalho de um instalador ou de uma sessão aberta). Arquivos soltos valem um por um."""
    if not idade_minima:
        todos = _todos(pasta)
        return [c for c, _, _ in todos], sum(t for _, t, _ in todos), 0
    arquivos, total, recentes = [], 0, 0
    for e in _entradas(pasta):
        try:
            if e.is_symlink() or getattr(e, "is_junction", lambda: False)():
                continue
            if e.is_dir(follow_symlinks=False):
                bloco = _todos(pasta / e.name)
            else:
                st = e.stat(follow_symlinks=False)
                bloco = [(pasta / e.name, st.st_size, st.st_mtime)]
        except OSError:
            continue
        if any(agora - m < idade_minima for _, _, m in bloco):
            recentes += len(bloco)
            continue
        arquivos += [c for c, _, _ in bloco]
        total += sum(t for _, t, _ in bloco)
    return arquivos, total, recentes


def processos_abertos() -> set[str]:  # pragma: no cover - lê a lista real de processos
    """Nomes dos .exe rodando agora (minúsculos), pelo `tasklist` do Windows."""
    try:
        saida = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=20,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {linha[0].casefold() for linha in csv.reader(io.StringIO(saida)) if linha}


def medir(
    ids: Iterable[str] | None = None,
    *,
    perfil: Path | None = None,
    abertos: Callable[[], set[str]] = processos_abertos,
    agora: float | None = None,
    parar: Callable[[], bool] = lambda: False,
) -> list[Achado]:
    """Quanto cada limpeza liberaria. Só lê."""
    agora = time.time() if agora is None else agora
    rodando = abertos()
    achados = []
    for limpeza in (POR_ID[i] for i in ids) if ids is not None else LIMPEZAS:
        if parar():
            break
        achado = Achado(limpeza, pastas=pastas_do_cache(limpeza.id, perfil))
        achado.navegador_aberto = bool(limpeza.navegador and limpeza.navegador.casefold() in rodando)
        for pasta in achado.pastas:
            arquivos, total, recentes = _arquivos(pasta, limpeza.idade_minima, agora)
            achado.arquivos += arquivos
            achado.bytes += total
            achado.recentes += recentes
        achados.append(achado)
    return achados


AVISOS = (
    "Tudo vai para a quarentena do C: (dá para desfazer). O espaço só é liberado quando você esvaziar.",
    "Arquivo em uso o Windows não deixa mover: ele fica e aparece como \"falhou\" (normal).",
)


def planejar(q: Quarentena, achados: Iterable[Achado], abertos: Callable[[], set[str]] = processos_abertos) -> Plano:
    """Prévia: os arquivos das limpezas escolhidas. Confere de novo se algum navegador abriu."""
    rodando = abertos()
    arquivos, titulos, ignorados = [], [], []
    for a in achados:
        if a.limpeza.navegador and a.limpeza.navegador.casefold() in rodando:
            ignorados.append((a.pastas[0] if a.pastas else Path(a.limpeza.titulo),
                              f"{a.limpeza.navegador} está aberto: feche o navegador"))
            continue
        if a.arquivos:
            arquivos += a.arquivos
            titulos.append(a.limpeza.titulo)
    plano = (q.planejar_mover(arquivos, descricao="limpeza: " + ", ".join(titulos)) if arquivos
             else Plano("quarentena", "limpeza"))
    plano.ignorados += ignorados
    plano.avisos += list(AVISOS)
    return plano
