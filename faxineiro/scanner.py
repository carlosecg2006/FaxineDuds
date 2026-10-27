"""Percorre uma pasta e atualiza o índice. Incremental: só relê o que mudou."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import Bloqueios
from .disco import no_disco, sem_prefixo
from .indice import Indice, Registro
from .tipos import TipoDetectado, detectar_tipo, tipo_pela_extensao

LOTE_COMMIT = 500
INTERVALO_PROGRESSO = 25


@dataclass
class Progresso:
    varridos: int = 0
    novos: int = 0
    alterados: int = 0
    iguais: int = 0
    removidos: int = 0
    ignorados: int = 0
    erros: int = 0
    pastas_ignoradas: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    terminou: bool = False
    cancelado: bool = False
    fora_por_bloqueio: int = 0  # linhas tiradas do índice por estarem em pasta bloqueada


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")


# Pastas no Windows (sem LongPathsEnabled) só funcionam até 248 caracteres; arquivos até 260.
# Desde a Fase 7B o scanner fala com o Windows usando o prefixo \\?\ (disco.no_disco) e indexa
# esses caminhos também; o aviso só aparece se mesmo assim o Windows recusar.
LIMITE_PASTA_WINDOWS = 248


def caminho_longo_demais(pasta: Path, erro: OSError) -> bool:
    return getattr(erro, "winerror", None) == 206 or len(str(pasta)) >= LIMITE_PASTA_WINDOWS


def _eh_link(entrada: os.DirEntry) -> bool:
    """Links simbólicos e junções do Windows não são seguidos (evita loops)."""
    if entrada.is_symlink():
        return True
    eh_juncao = getattr(entrada, "is_junction", None)
    return bool(eh_juncao and eh_juncao())


def _percorrer(
    raiz: Path, bloqueios: Bloqueios, progresso: Progresso, pastas_com_erro: list[str]
) -> Iterator[tuple[str, os.stat_result]]:
    """Devolve (caminho sem prefixo, stat) de cada arquivo."""
    pilha = [raiz]
    while pilha:
        pasta = pilha.pop()
        try:
            with os.scandir(no_disco(pasta)) as entradas:
                lista = list(entradas)
        except OSError as erro:
            progresso.erros += 1
            if caminho_longo_demais(pasta, erro):
                progresso.avisos.append(
                    f"Caminho longo demais para o Windows (mais de 260 caracteres), não indexado: {pasta}"
                )
            else:
                progresso.avisos.append(f"Pasta inacessível: {pasta} ({erro.strerror})")
            pastas_com_erro.append(str(pasta))
            continue

        for entrada in lista:
            caminho = sem_prefixo(entrada.path)
            try:
                if _eh_link(entrada):
                    progresso.ignorados += 1
                    continue
                if entrada.is_dir(follow_symlinks=False):
                    if bloqueios.bloqueada(caminho):
                        progresso.ignorados += 1
                        progresso.pastas_ignoradas.append(caminho)
                    else:
                        pilha.append(Path(caminho))
                elif entrada.is_file(follow_symlinks=False):
                    yield caminho, entrada.stat(follow_symlinks=False)
            except OSError as erro:
                progresso.erros += 1
                progresso.avisos.append(f"Erro em {caminho}: {erro.strerror}")


def _montar_registro(
    caminho: str,
    st: os.stat_result,
    pasta_raiz: str,
    aparelho: str,
    detector: Callable[[Path], TipoDetectado],
) -> Registro:
    nome = Path(caminho).name
    conectado = True
    if so_na_nuvem(st):
        # OneDrive/Dropbox "só na nuvem": ABRIR baixaria o arquivo inteiro (e encheria o disco).
        # Fica no índice só com o que a listagem da pasta já diz; o tipo vem da extensão.
        tipo = tipo_pela_extensao(Path(nome).suffix)
        aparelho, conectado = "nuvem", False
    else:
        tipo = detector(Path(caminho))
    return Registro(
        caminho=caminho,
        pasta_raiz=pasta_raiz,
        nome=nome,
        extensao=Path(nome).suffix.lower().lstrip("."),
        tamanho=st.st_size,
        criado_em=_iso(getattr(st, "st_birthtime", st.st_ctime)),
        modificado_em=_iso(st.st_mtime),
        modificado_ns=st.st_mtime_ns,
        tipo_real=tipo.tipo_real,
        categoria=tipo.categoria,
        extensao_confere=tipo.extensao_confere,
        aparelho=aparelho,
        conectado=conectado,
    )


# Atributos do Windows que marcam arquivo que não está (todo) no disco: abrir faz o download.
_ATRIBUTOS_SO_NA_NUVEM = 0x00400000 | 0x00040000 | 0x00001000  # RECALL_ON_DATA_ACCESS | RECALL_ON_OPEN | OFFLINE


def so_na_nuvem(st: os.stat_result) -> bool:
    """True para arquivo "só na nuvem" (OneDrive Arquivos Sob Demanda etc.). Lê o atributo da
    listagem da pasta — o arquivo não é aberto, então nada é baixado."""
    return bool(getattr(st, "st_file_attributes", 0) & _ATRIBUTOS_SO_NA_NUVEM)


def indexar_arquivo(
    caminho: str | Path,
    indice: Indice,
    pasta_raiz: str,
    *,
    aparelho: str = "pc",
    detector: Callable[[Path], TipoDetectado] = detectar_tipo,
) -> None:
    """Coloca (ou atualiza) um único arquivo no índice, sem varrer a pasta inteira."""
    caminho = str(Path(caminho).resolve())
    st = os.stat(no_disco(caminho))
    indice.gravar(_montar_registro(caminho, st, pasta_raiz, aparelho, detector), 0, _agora())


def escanear(
    pasta: str | Path,
    indice: Indice,
    *,
    aparelho: str = "pc",
    bloqueios: Bloqueios | None = None,
    ao_progredir: Callable[[Progresso], None] | None = None,
    detector: Callable[[Path], TipoDetectado] = detectar_tipo,
    parar: Callable[[], bool] = lambda: False,
) -> Progresso:
    """Varre `pasta` e atualiza o índice. Nunca altera os arquivos do usuário.

    `parar()` é consultado entre um arquivo e outro (botão Cancelar da interface)."""
    raiz = Path(pasta).resolve()
    if not raiz.is_dir():
        raise NotADirectoryError(f"Pasta não encontrada: {raiz}")

    bloqueios = bloqueios or Bloqueios()
    progresso = Progresso()
    pasta_raiz = str(raiz)
    # Pasta que passou a ser bloqueada (ex.: FileHistory): as linhas antigas saem do índice já,
    # sem esperar a varredura terminar. Só a pasta pedida e as de dentro dela contam.
    progresso.fora_por_bloqueio = indice.remover_bloqueados(
        lambda p: bloqueios.bloqueada(p) and (p == raiz or raiz in p.parents), prefixo=pasta_raiz)
    anteriores = indice.assinaturas(pasta_raiz)
    varredura_id = indice.iniciar_varredura(pasta_raiz, aparelho, _agora())
    pastas_com_erro: list[str] = []
    iguais_pendentes: list[str] = []

    def avisar() -> None:
        if ao_progredir:
            ao_progredir(progresso)

    for caminho, st in _percorrer(raiz, bloqueios, progresso, pastas_com_erro):
        if parar():
            progresso.cancelado = True
            break
        progresso.varridos += 1
        assinatura = (st.st_size, st.st_mtime_ns)
        anterior = anteriores.get(caminho)

        if anterior == assinatura:
            progresso.iguais += 1
            iguais_pendentes.append(caminho)
        else:
            try:
                registro = _montar_registro(caminho, st, pasta_raiz, aparelho, detector)
            except OSError as erro:
                progresso.erros += 1
                progresso.avisos.append(f"Não consegui ler {caminho}: {erro.strerror}")
                continue
            indice.gravar(registro, varredura_id, _agora())
            if anterior is None:
                progresso.novos += 1
            else:
                progresso.alterados += 1

        if len(iguais_pendentes) >= LOTE_COMMIT:
            indice.marcar_visto(iguais_pendentes, varredura_id)
            iguais_pendentes.clear()
        if progresso.varridos % LOTE_COMMIT == 0:
            indice.confirmar()
        if progresso.varridos % INTERVALO_PROGRESSO == 0:
            avisar()

    # Arquivos dentro de pastas que não deu para ler continuam no índice.
    if pastas_com_erro:
        prefixos = tuple(p.rstrip("\\/") + os.sep for p in pastas_com_erro)
        iguais_pendentes.extend(c for c in anteriores if c.startswith(prefixos))
    indice.marcar_visto(iguais_pendentes, varredura_id)
    if progresso.cancelado:
        # Cancelada no meio: o que não foi visto NÃO sumiu, só não deu tempo de olhar. Não remove nada.
        indice.confirmar()
    else:
        progresso.removidos = indice.remover_nao_vistos(pasta_raiz, varredura_id)
    indice.finalizar_varredura(
        varredura_id,
        _agora(),
        novos=progresso.novos,
        alterados=progresso.alterados,
        iguais=progresso.iguais,
        removidos=progresso.removidos,
        ignorados=progresso.ignorados,
        erros=progresso.erros,
    )
    progresso.terminou = True
    avisar()
    return progresso
