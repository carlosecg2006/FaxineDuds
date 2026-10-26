"""Configurações: pastas bloqueadas, caminho do índice e trava de desenvolvimento."""

from __future__ import annotations

import os
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
PASTA_TESTE = RAIZ_PROJETO / "pasta_teste"
CAMINHO_INDICE = RAIZ_PROJETO / "dados" / "indice.sqlite"

# Caminhos absolutos que nunca são varridos (regra 3 do CLAUDE.md).
CAMINHOS_BLOQUEADOS: tuple[str, ...] = (
    r"C:\Windows",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    r"C:\ProgramData",
)

# Nomes de pasta bloqueados em qualquer lugar da árvore.
NOMES_BLOQUEADOS: tuple[str, ...] = (
    "AppData",
    "$Recycle.Bin",
    "System Volume Information",
    "_quarentena",
    ".git",
    ".venv",
)


# Quarentena (Fase 3)
NOME_QUARENTENA = "_quarentena"


def pasta_quarentena(arquivo: str | Path, modo_dev: bool = True) -> Path:
    """Onde fica a quarentena de um arquivo: sempre na MESMA unidade (mover = renomear, sem cópia).

    Durante o desenvolvimento (regra 5) é `pasta_teste\\_quarentena`; na Fase 7 passa a ser
    a raiz da unidade do arquivo, ex.: `D:\\_quarentena`.
    """
    if modo_dev:
        return PASTA_TESTE / NOME_QUARENTENA
    return Path(Path(arquivo).resolve().anchor) / NOME_QUARENTENA


# IA local (Fase 4) — ajustada para PC com 4 GB de RAM.
# Para trocar de modelo: variável de ambiente FAXINEIRO_MODELO ou --modelo nos comandos `ia`.
MODELO_IA = os.environ.get("FAXINEIRO_MODELO", "qwen2.5:0.5b")
IA_NUM_CTX = 1024  # janela de contexto pequena = menos memória (o prompt cortado cabe com folga)
IA_KEEP_ALIVE = "30s"  # o Ollama solta o modelo da memória logo depois de terminar
IA_FATOR_MEMORIA = 1.2  # o modelo ocupa ~20% a mais que o arquivo dele, carregado
IA_MARGEM_MEMORIA = 250 * 1024 * 1024  # folga para o Windows e os outros programas


# Ordem em que a IA trabalha: primeiro Downloads, depois Área de Trabalho, Documentos e o resto.
PRIORIDADE_PASTAS: tuple[tuple[str, ...], ...] = (
    ("downloads",),
    ("desktop", "área de trabalho", "area de trabalho"),
    ("documents", "documentos", "meus documentos"),
)

# "Pastas-bloco": projetos e programas. Tratadas como uma unidade — nunca se organiza o que está dentro.
BLOCO_MARCADORES: tuple[str, ...] = (  # se a pasta tem um destes (arquivo ou pasta), é bloco
    ".git", ".hg", ".svn", "package.json", "pyproject.toml", "setup.py", "requirements.txt",
    "Pipfile", "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "CMakeLists.txt", "Makefile",
    "composer.json", "Gemfile", "pubspec.yaml", "node_modules", ".venv", "venv", "pyvenv.cfg",
    ".idea", ".vscode", "steam_appid.txt",
)
BLOCO_PADROES: tuple[str, ...] = ("*.sln", "*.csproj", "*.vcxproj", "*.xcodeproj", "*.sav", "*.save")
BLOCO_NOMES_DE_PASTA: tuple[str, ...] = (  # a própria pasta, pelo nome, já é bloco
    "Saved Games", "My Games", "SaveGames", "Saves", "steamapps", "node_modules", "site-packages",
)

# Pastas sincronizadas com a nuvem: nunca organizar (mover para fora APAGA o arquivo da nuvem).
NUVEM_NOMES: tuple[str, ...] = (
    "OneDrive", "Google Drive", "GoogleDrive", "Meu Drive", "My Drive", "Dropbox",
    "iCloudDrive", "iCloud Drive", "Box", "MEGA", "pCloud Drive",
)
NUVEM_PREFIXOS: tuple[str, ...] = ("OneDrive - ",)  # ex.: "OneDrive - Faculdade"
NUVEM_VARIAVEIS: tuple[str, ...] = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")


# Conversor (Fase 5B). ffmpeg baixado para D:\FaxineDuds\externos (nada instalado no Windows).
PASTA_EXTERNOS = RAIZ_PROJETO / "externos"
FFMPEG_THREADS = 2  # PC com 4 GB: não deixar o ffmpeg tomar o PC inteiro
IMAGEM_MAX_PIXELS = 120_000_000  # acima disso o Pillow recusa (evita estourar a RAM)


# Raio-X (Fase 2): o que conta como arquivo temporário / lixo.
TEMP_EXTENSOES: set[str] = {"tmp", "temp", "crdownload", "part", "partial"}
TEMP_PREFIXOS: tuple[str, ...] = ("~$",)  # rascunhos do Office
TEMP_NOMES: set[str] = {"thumbs.db", ".ds_store"}
TOP_PESADOS = 20
MB = 1024 * 1024
PESADO_MINIMO = 100 * MB  # só conta como "pesado" a partir daqui
PESADO_MINIMO_TESTE = 1 * MB  # modo de teste (--teste), para os arquivos pequenos da pasta_teste


class Bloqueios:
    """Decide se uma pasta deve ser ignorada. Comparação sem maiúsculas/minúsculas."""

    def __init__(
        self,
        caminhos: tuple[str, ...] | list[str] = CAMINHOS_BLOQUEADOS,
        nomes: tuple[str, ...] | list[str] = NOMES_BLOQUEADOS,
    ) -> None:
        self._caminhos = [self._normalizar(c) for c in caminhos]
        self._nomes = {n.casefold() for n in nomes}

    @staticmethod
    def _normalizar(caminho: str | Path) -> str:
        return str(Path(caminho)).rstrip("\\/").casefold()

    def bloqueada(self, pasta: str | Path) -> bool:
        pasta = Path(pasta)
        if pasta.name.casefold() in self._nomes:
            return True
        texto = self._normalizar(pasta)
        return any(texto == c or texto.startswith(c + "\\") or texto.startswith(c + "/")
                   for c in self._caminhos)


def dentro_da_pasta_teste(pasta: str | Path, pasta_teste: Path = PASTA_TESTE) -> bool:
    """Trava de desenvolvimento (regra 5): só aceita pastas dentro de pasta_teste."""
    alvo = Path(pasta).resolve()
    base = pasta_teste.resolve()
    return alvo == base or base in alvo.parents
