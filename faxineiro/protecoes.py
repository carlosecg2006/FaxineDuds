"""Onde o organizar NUNCA mexe: pastas bloqueadas, pastas da nuvem e pastas-bloco.

- Pasta-bloco: projeto ou programa (tem .git, package.json, .sln, .exe com DLLs, saves de jogo...).
  A pasta inteira é uma unidade: tirar um arquivo de dentro quebra o projeto/jogo.
- Pasta da nuvem (OneDrive, Google Drive, Dropbox...): mover um arquivo para fora dela
  APAGA o arquivo da nuvem.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from . import config
from .config import Bloqueios


class Protecoes:
    def __init__(
        self,
        *,
        bloqueios: Bloqueios | None = None,
        marcadores: tuple[str, ...] = config.BLOCO_MARCADORES,
        padroes: tuple[str, ...] = config.BLOCO_PADROES,
        nomes_de_pasta: tuple[str, ...] = config.BLOCO_NOMES_DE_PASTA,
        nuvem_nomes: tuple[str, ...] = config.NUVEM_NOMES,
        nuvem_prefixos: tuple[str, ...] = config.NUVEM_PREFIXOS,
        nuvem_pastas: list[str] | None = None,
    ) -> None:
        self.bloqueios = bloqueios or Bloqueios()
        self.marcadores = {m.casefold() for m in marcadores}
        self.padroes = tuple(p.casefold() for p in padroes)
        self.nomes_de_pasta = {n.casefold() for n in nomes_de_pasta}
        self.nuvem_nomes = {n.casefold() for n in nuvem_nomes}
        self.nuvem_prefixos = tuple(p.casefold() for p in nuvem_prefixos)
        if nuvem_pastas is None:  # pastas que o próprio Windows diz serem do OneDrive
            nuvem_pastas = [os.environ[v] for v in config.NUVEM_VARIAVEIS if os.environ.get(v)]
        self.nuvem_pastas = [Path(p).resolve() for p in nuvem_pastas]
        self._cache_bloco: dict[Path, str | None] = {}

    # --- pasta-bloco ---------------------------------------------------------------

    def motivo_bloco(self, pasta: Path) -> str | None:
        """Se `pasta` é projeto/programa, diz por quê. Olha só o conteúdo direto da pasta."""
        pasta = Path(pasta)
        if pasta in self._cache_bloco:
            return self._cache_bloco[pasta]
        motivo = None
        if pasta.name.casefold() in self.nomes_de_pasta:
            motivo = f"pasta de jogo/programa ({pasta.name})"
        else:
            try:
                nomes = [e.name for e in os.scandir(pasta)]
            except OSError:
                nomes = []
            baixos = [n.casefold() for n in nomes]
            for nome, baixo in zip(nomes, baixos):
                if baixo in self.marcadores:
                    motivo = f"projeto/programa (tem {nome})"
                    break
                if any(fnmatch.fnmatch(baixo, p) for p in self.padroes):
                    motivo = f"projeto/jogo (tem {nome})"
                    break
            if motivo is None and any(b.endswith(".exe") for b in baixos) and any(b.endswith(".dll") for b in baixos):
                motivo = "programa instalado (tem .exe junto com DLLs)"
        self._cache_bloco[pasta] = motivo
        return motivo

    def bloco_que_contem(self, caminho: Path, base: Path) -> tuple[Path, str] | None:
        """A pasta-bloco mais de cima (entre `base` e o arquivo) que contém `caminho`."""
        caminho, base = Path(caminho), Path(base)
        pastas = [p for p in reversed(caminho.parents) if p == base or base in p.parents]
        for pasta in pastas:
            motivo = self.motivo_bloco(pasta)
            if motivo:
                return pasta, motivo
        return None

    # --- nuvem -----------------------------------------------------------------------

    def nuvem(self, caminho: Path) -> str | None:
        """Nome do serviço de nuvem se `caminho` está numa pasta sincronizada."""
        caminho = Path(caminho).resolve()
        for raiz in self.nuvem_pastas:
            if caminho == raiz or raiz in caminho.parents:
                return raiz.name
        for parte in caminho.parts[:-1]:
            baixo = parte.casefold()
            if baixo in self.nuvem_nomes or baixo.startswith(self.nuvem_prefixos):
                return parte
        return None

    # --- decisão final -----------------------------------------------------------------

    def motivo_para_nao_organizar(self, caminho: Path, base: Path) -> str | None:
        """None = pode organizar. Senão, o motivo (para mostrar na prévia)."""
        caminho = Path(caminho)
        for pasta in caminho.parents:
            if self.bloqueios.bloqueada(pasta):
                return "pasta bloqueada"
            if pasta == base:
                break
        servico = self.nuvem(caminho)
        if servico:
            return f"pasta sincronizada com a nuvem ({servico}): mover para fora apagaria da nuvem"
        bloco = self.bloco_que_contem(caminho, base)
        if bloco:
            return f"dentro de pasta-bloco {bloco[0].name} — {bloco[1]}"
        return None

    def motivo_para_nao_mexer(self, caminho: Path, area: Path) -> str | None:
        """Fase 7B — vale para TODA ação que muda o disco (quarentena, mover de unidade, converter).
        None = pode. Olha da `area` para baixo: a própria raiz da área não conta como pasta-bloco
        (C:\\Users\\<usuário> tem .vscode, o D:\\ tem instaladores .exe soltos)."""
        caminho, area = Path(caminho), Path(area)
        abaixo = [p for p in caminho.parents if area in p.parents]  # do arquivo para cima, sem a área
        if any(self.bloqueios.bloqueada(p) for p in abaixo):
            return "dentro de pasta bloqueada (regra 3): não mexo"
        servico = self.nuvem(caminho)
        if servico:
            return f"pasta sincronizada com a nuvem ({servico}): não mexo"
        for pasta in reversed(abaixo):
            motivo = self.motivo_bloco(pasta)
            if motivo:
                return f"dentro de pasta-bloco {pasta.name} — {motivo}: não mexo"
        return None

    def destino_proibido(self, destino: Path, base: Path) -> str | None:
        """O destino também não pode ser pasta da nuvem nem bloqueada (de `base` para baixo)."""
        servico = self.nuvem(destino)
        if servico:
            return f"destino em pasta da nuvem ({servico})"
        for pasta in Path(destino).parents:
            if pasta == base:
                break
            if self.bloqueios.bloqueada(pasta):
                return "destino em pasta bloqueada"
        return None


# --- Fase 7B: a mesma trava para toda ação que muda o disco --------------------------


def protecoes_para(area: Path) -> Protecoes:
    """Na pasta_teste (e em pastas de teste), os bloqueios de sempre; no PC real, também a pasta
    do próprio app (índice, .venv, ffmpeg...)."""
    no_pc = (config.area_de(area, config.AREAS_DE_LEITURA) is not None
             and config.area_de(area, (config.PASTA_TESTE,)) is None)
    return Protecoes(bloqueios=config.bloqueios_do_pc() if no_pc else Bloqueios())


def cache_liberado(caminho: str | Path) -> str | None:
    """Fase 7C.3: se `caminho` está DENTRO de uma pasta de `config.CACHES_LIBERADOS` (nunca a
    própria pasta), devolve qual ("temp", "chrome"...). É a única exceção ao bloqueio do AppData."""
    partes = tuple(p.casefold() for p in Path(caminho).parts)
    perfil = tuple(p.casefold() for p in Path(config.PASTA_DO_USUARIO).parts)
    if partes[:len(perfil)] != perfil:
        return None
    resto = partes[len(perfil):]
    for chave, padroes in config.CACHES_LIBERADOS.items():
        for padrao in padroes:
            pedacos = [p.casefold() for p in padrao.split("\\")]
            if len(resto) > len(pedacos) and all(fnmatch.fnmatchcase(a, b) for a, b in zip(resto, pedacos)):
                return chave
    return None


def fora_da_area(caminho: Path, areas: tuple[Path, ...]) -> str:
    if config.area_de(caminho, config.AREAS_DE_LEITURA) is not None:
        return "fora da área permitida: ligue o modo PC real para mexer aqui (menu Segurança)"
    return f"fora da área permitida ({', '.join(str(a) for a in areas)})"


def motivo_para_acao(caminho: Path, areas: tuple[Path, ...]) -> str | None:
    """None = a ação pode mexer em `caminho`. Fora das áreas, pasta bloqueada, nuvem, pasta-bloco
    e pasta de programa: nunca."""
    area = config.area_de(caminho, areas)
    if area is None:
        return fora_da_area(caminho, areas)
    return protecoes_para(area).motivo_para_nao_mexer(Path(caminho), area)
