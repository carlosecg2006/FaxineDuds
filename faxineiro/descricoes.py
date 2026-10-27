"""Descreve cada arquivo do índice: IA local quando dá, regras simples quando não dá.

- Texto e documentos: manda nome + pasta + só o COMEÇO do conteúdo (já cortado).
- Imagens: só com modelo de visão instalado; senão, regras.
- O resto: nome, tipo, tamanho e data (sem conteúdo).
- Processa em lotes e grava a cada lote; pode pausar e continuar depois.
"""

from __future__ import annotations

import base64
import os
import re
import sqlite3
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from . import config
from .extracao import comeco_do_texto
from .formato import formatar_bytes
from .ia import IAIndisponivel, IATempoEsgotado, StatusIA, avaliar_ia
from .indice import Indice
from .memoria import memoria_disponivel
from .raiox import prefixo_da_pasta

TIPOS_COM_TEXTO = {"texto", "docx", "xlsx", "pptx", "pdf"}
IMAGEM_MAX_BYTES = 10 * 1024 * 1024  # imagens maiores não vão para o modelo de visão

_NOME_CATEGORIA = {
    "imagem": "Imagem", "documento": "Documento", "texto": "Arquivo de texto", "audio": "Áudio",
    "video": "Vídeo", "compactado": "Arquivo compactado", "executavel": "Programa", "outro": "Arquivo",
}
_MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

# Tipos que se explicam pela extensão: as regras descrevem, sem IA.
EXTENSOES_OBVIAS = {
    "log": "Arquivo de log", "py": "Código-fonte Python", "js": "Código JavaScript", "ts": "Código TypeScript",
    "java": "Código Java", "c": "Código C", "cpp": "Código C++", "h": "Cabeçalho C/C++", "cs": "Código C#",
    "html": "Página HTML", "htm": "Página HTML", "css": "Folha de estilo CSS", "json": "Dados JSON",
    "xml": "Dados XML", "yaml": "Configuração YAML", "yml": "Configuração YAML", "ini": "Configuração",
    "cfg": "Configuração", "toml": "Configuração TOML", "sql": "Script SQL", "bat": "Script do Windows",
    "ps1": "Script PowerShell", "sh": "Script de shell", "srt": "Legenda de vídeo",
}
# Palavras que não dizem nada sobre o conteúdo ("Novo documento (2).docx", "scan_0001.pdf").
PALAVRAS_GENERICAS = {
    "documento", "document", "doc", "arquivo", "file", "novo", "nova", "new", "copia", "cópia", "copy",
    "sem", "titulo", "título", "untitled", "scan", "digitalizado", "digitalizacao", "img", "image", "imagem",
    "foto", "final", "teste", "test", "temp", "tmp", "download", "downloads", "anexo", "attachment", "texto",
    "text", "planilha", "apresentacao", "apresentação", "pasta", "desktop", "documentos", "documents",
    "area", "área", "trabalho", "outros", "diversos", "misc", "versao", "versão", "rev", "the", "and",
}
_SEPARA_PALAVRAS = re.compile(r"[\s_\-.()\[\]]+|(?<=[a-zà-ú])(?=[A-Z])")


class ClienteIA(Protocol):
    def status(self) -> StatusIA: ...
    def gerar(self, prompt: str, *, timeout: float = ..., imagens: list[str] | None = ...,
              modelo: str | None = ..., formato_json: bool = ..., max_tokens: int = ...) -> str: ...


@dataclass
class ConfigDescricao:
    timeout: float = 60  # por arquivo
    timeout_aquecimento: float = 180  # 1ª chamada: o Ollama ainda está carregando o modelo
    tamanho_lote: int = 10
    pausa_entre_arquivos: float = 0.1  # deixa o PC respirar
    max_falhas_seguidas: int = 3


@dataclass
class ProgressoDescricao:
    total: int = 0
    feitos: int = 0
    por_ia: int = 0
    por_visao: int = 0
    por_regras: int = 0
    revisar: int = 0
    lotes_gravados: int = 0
    pausado: bool = False
    ia_ligada: bool = False
    terminou: bool = False
    avisos: list[str] = field(default_factory=list)
    fase: str = ""  # "inicio" (antes da IA), "estimativa" (já mediu), "lote", "fim"
    tempos: list[float] = field(default_factory=list)  # segundos por arquivo na IA (sem o aquecimento)

    @property
    def faltam(self) -> int:
        return max(self.total - self.feitos, 0)

    @property
    def estimativa_s(self) -> float | None:
        """Segundos que ainda faltam, pela média dos arquivos já medidos (None se ainda não mediu)."""
        if not self.tempos:
            return None
        return sum(self.tempos) / len(self.tempos) * self.faltam


ARQUIVOS_PARA_MEDIR = 3  # a estimativa sai depois de medir estes primeiros arquivos


def _pasta_relativa(linha: sqlite3.Row) -> str:
    pai = Path(linha["caminho"]).parent
    try:
        rel = pai.relative_to(Path(linha["pasta_raiz"]))
        return str(rel) if str(rel) != "." else "(pasta principal)"
    except ValueError:
        return pai.name


def _mes_ano(iso: str | None) -> str:
    if not iso:
        return "data desconhecida"
    d = datetime.fromisoformat(iso)
    return f"{_MESES[d.month - 1]}/{d.year}"


def descricao_por_regras(linha: sqlite3.Row) -> str:
    """Descrição sem IA, só com o que o índice já sabe."""
    tipo = linha["tipo_real"] or "desconhecido"
    if tipo == "vazio":
        inicio = "Arquivo vazio"
    elif linha["extensao"] in EXTENSOES_OBVIAS:
        inicio = EXTENSOES_OBVIAS[linha["extensao"]]
    elif tipo == "desconhecido":
        inicio = "Arquivo de tipo desconhecido"
    elif tipo == "texto":
        inicio = f"Arquivo de texto (.{linha['extensao']})" if linha["extensao"] else "Arquivo de texto"
    else:
        inicio = f"{_NOME_CATEGORIA.get(linha['categoria'], 'Arquivo')} {tipo.upper()}"
    return (f"{inicio} com o nome '{linha['nome']}' em '{_pasta_relativa(linha)}', "
            f"{formatar_bytes(linha['tamanho'])}, modificado em {_mes_ano(linha['modificado_em'])}.")


def montar_prompt(linha: sqlite3.Row, texto: str | None) -> str:
    partes = [
        "Você descreve arquivos de um computador pessoal. Responda em português do Brasil, "
        "em UMA frase curta (no máximo 20 palavras), dizendo o que o arquivo provavelmente é. "
        "Não invente detalhes que não aparecem nos dados.",
        "",
        f"Nome: {linha['nome']}",
        f"Pasta: {_pasta_relativa(linha)}",
        f"Tipo: {linha['tipo_real']} ({linha['categoria']})",
        f"Tamanho: {formatar_bytes(linha['tamanho'])}",
        f"Modificado: {_mes_ano(linha['modificado_em'])}",
    ]
    if texto:
        partes += ["Começo do conteúdo (cortado):", '"""', texto, '"""']
    partes += ["", "Descrição:"]
    return "\n".join(partes)


def _limpar_resposta(resposta: str) -> str:
    linha = resposta.strip().splitlines()[0] if resposta.strip() else ""
    linha = linha.removeprefix("Descrição:").strip().strip('"').strip("'").strip()
    # Modelos pequenos às vezes "desandam" numa lista; fica com a 1ª frase e no máximo 25 palavras.
    if ". " in linha:
        linha = linha.split(". ")[0] + "."
    palavras = linha.split()
    if len(palavras) > 25:
        linha = " ".join(palavras[:25]).rstrip(",;:") + "…"
    return linha[:240]


def baixar_prioridade() -> None:
    """Deixa o processo do Faxineiro com prioridade 'abaixo do normal' (Windows)."""
    if sys.platform == "win32":
        import ctypes

        BELOW_NORMAL_PRIORITY_CLASS = 0x4000
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),
                                                BELOW_NORMAL_PRIORITY_CLASS)
    else:  # pragma: no cover - só para quem rodar fora do Windows
        os.nice(10)


class _Descritor:
    """Guarda o estado de uma rodada: IA ligada?, já aqueceu?, falhas seguidas."""

    def __init__(self, cliente: ClienteIA | None, cfg: ConfigDescricao, progresso: ProgressoDescricao,
                 memoria: Callable[[], int | None] = memoria_disponivel):
        self.cliente = cliente
        self.cfg = cfg
        self.progresso = progresso
        self.memoria = memoria
        self.aquecido = False
        self.falhas_seguidas = 0
        self.usou_ia = False
        st, self.usar_ia, aviso = avaliar_ia(cliente, memoria)
        self.modelo_visao = st.modelo_visao if self.usar_ia else None
        progresso.ia_ligada = self.usar_ia
        if aviso:
            progresso.avisos.append(aviso)

    def conferir_memoria(self) -> None:
        """Entre um lote e outro: se a memória livre caiu demais, para a IA antes de travar o PC."""
        if not self.usar_ia or self.usou_ia:  # modelo já carregado: não precisa de memória nova
            return
        _, ok, aviso = avaliar_ia(self.cliente, self.memoria)
        if not ok:
            self.usar_ia = False
            self.progresso.avisos.append(aviso or "IA desligada nesta rodada.")

    def terminar(self) -> None:
        """Libera a memória do modelo assim que a rodada acaba."""
        if self.usou_ia and hasattr(self.cliente, "descarregar"):
            self.cliente.descarregar()

    def _chamar(self, prompt: str, **kw) -> str | None:
        timeout = self.cfg.timeout if self.aquecido else self.cfg.timeout_aquecimento
        try:
            resposta = self.cliente.gerar(prompt, timeout=timeout, **kw)
        except IAIndisponivel as erro:
            self.falhas_seguidas += 1
            tipo = "demorou demais" if isinstance(erro, IATempoEsgotado) else "falhou"
            self.progresso.avisos.append(f"IA {tipo}: {erro}")
            if self.falhas_seguidas >= self.cfg.max_falhas_seguidas:
                self.usar_ia = False
                self.progresso.avisos.append(
                    f"{self.falhas_seguidas} falhas seguidas: o resto desta rodada usa regras simples.")
            return None
        self.aquecido = True
        self.usou_ia = True
        self.falhas_seguidas = 0
        return _limpar_resposta(resposta) or None

    def descrever_com_ia(self, linha: sqlite3.Row) -> tuple[str, str, bool] | None:
        """Tenta a IA. Devolve (descrição, origem, revisar) ou None se não deu."""
        if _so_na_nuvem(linha):
            self.progresso.avisos.append(f"{linha['nome']} está só na nuvem: não abro (baixaria o arquivo).")
            return None
        if self.usar_ia:
            if linha["categoria"] == "imagem":
                if self.modelo_visao and linha["tamanho"] <= IMAGEM_MAX_BYTES:
                    try:
                        imagem = base64.b64encode(Path(linha["caminho"]).read_bytes()).decode("ascii")
                    except OSError:
                        imagem = None
                    if imagem:
                        resp = self._chamar(montar_prompt(linha, None), imagens=[imagem], modelo=self.modelo_visao)
                        if resp:
                            return resp, "ia_visao", False
            else:
                texto = (comeco_do_texto(linha["caminho"], linha["tipo_real"])
                         if linha["tipo_real"] in TIPOS_COM_TEXTO else None)
                resp = self._chamar(montar_prompt(linha, texto))
                if resp:
                    return resp, "ia", False
        return None


def palavras_uteis(texto: str) -> list[str]:
    """Palavras que dizem algo: 3+ letras e não genéricas ("Novo", "scan", "cópia"...)."""
    return [p for p in _SEPARA_PALAVRAS.split(texto)
            if len(p) >= 3 and p.isalpha() and p.casefold() not in PALAVRAS_GENERICAS]


def obvio_pelo_nome(linha: sqlite3.Row) -> bool:
    """Nome + pasta já explicam o arquivo? Ex.: 'Faculdade/resumo_redes.txt' sim; 'Downloads/scan_0001.pdf' não."""
    caminho = Path(linha["caminho"])
    return len(palavras_uteis(caminho.stem) + palavras_uteis(caminho.parent.name)) >= 2


def _so_na_nuvem(linha) -> bool:
    try:
        return linha["aparelho"] == "nuvem"
    except (KeyError, IndexError):
        return False


def precisa_ia(linha: sqlite3.Row) -> bool:
    """IA seletiva: as regras resolvem o óbvio pelo tipo, pelo nome e pela pasta.

    - Óbvio pelo tipo: fotos, vídeos, músicas, programas, zips, vazios, código, logs, configurações.
    - Óbvio pelo nome/pasta: 'Faculdade/resumo_redes.txt', 'boleto_luz_outubro.pdf'.
    - Precisa de IA: texto/documento com nome genérico ('Novo documento.docx', 'scan_0001.pdf')
      e arquivos de tipo desconhecido.
    """
    if (linha["tamanho"] or 0) == 0 or _so_na_nuvem(linha):
        return False  # só na nuvem: ler o conteúdo baixaria o arquivo
    if linha["tipo_real"] == "desconhecido":
        return True
    if linha["categoria"] not in ("texto", "documento"):
        return False
    if linha["extensao"] in EXTENSOES_OBVIAS:
        return False
    return not obvio_pelo_nome(linha)


def prioridade(caminho: str | Path) -> int:
    """0 = Downloads, 1 = Área de Trabalho, 2 = Documentos, 3 = o resto (config.PRIORIDADE_PASTAS)."""
    partes = {p.casefold() for p in Path(caminho).parts[:-1]}
    for nivel, nomes in enumerate(config.PRIORIDADE_PASTAS):
        if partes & set(nomes):
            return nivel
    return len(config.PRIORIDADE_PASTAS)


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def descrever(
    indice: Indice,
    pasta: str | Path,
    cliente: ClienteIA | None,
    *,
    limite: int | None = None,
    so_regras: bool = False,
    parar: Callable[[], bool] = lambda: False,
    ao_progredir: Callable[[ProgressoDescricao], None] | None = None,
    cfg: ConfigDescricao | None = None,
    dormir: Callable[[float], None] = time.sleep,
    memoria: Callable[[], int | None] = memoria_disponivel,
    relogio: Callable[[], float] = time.monotonic,
) -> ProgressoDescricao:
    """IA seletiva, em duas etapas:

    1. Regras descrevem TODOS os arquivos novos/alterados (rápido, sem IA). O que é óbvio
       fica pronto; texto, documentos e desconhecidos ficam marcados "revisar".
    2. A IA descreve só os marcados "revisar" — se o Ollama estiver ligado e houver memória.

    Rodar de novo continua de onde parou (o estado fica no índice).
    """
    cfg = cfg or ConfigDescricao()
    progresso = ProgressoDescricao()
    prefixo = prefixo_da_pasta(pasta)

    # Etapa 1: regras para tudo que ainda não tem descrição.
    novos = indice.pendentes_de_descricao(prefixo)
    for linha in novos:
        revisar = precisa_ia(linha)
        indice.gravar_descricao(linha["id"], descricao_por_regras(linha), "regras", revisar, _agora())
        progresso.por_regras += 1
    # Regras melhoraram desde a última rodada? Quem estava na fila e agora é óbvio sai da fila.
    for linha in indice.pendentes_de_revisao(prefixo):
        if linha["descricao_origem"] == "regras" and not precisa_ia(linha):
            indice.gravar_descricao(linha["id"], descricao_por_regras(linha), "regras", False, _agora())
    indice.confirmar()

    # Etapa 2: IA só no que as regras deixaram para revisar.
    # Ordem de prioridade: Downloads, Área de Trabalho, Documentos, depois o resto.
    revisao = sorted(indice.pendentes_de_revisao(prefixo), key=lambda l: (prioridade(l["caminho"]), l["caminho"]))
    para_ia = [] if so_regras else revisao[:limite] if limite is not None else revisao
    progresso.total = len(para_ia)
    progresso.revisar = len(revisao)

    def avisar(fase: str) -> None:
        progresso.fase = fase
        if ao_progredir:
            ao_progredir(progresso)

    if not para_ia:
        progresso.terminou = True
        avisar("fim")
        return progresso

    avisar("inicio")  # antes da IA: quantos faltam (a estimativa vem depois de medir os primeiros)
    d = _Descritor(cliente, cfg, progresso, memoria)
    try:
        for linha in para_ia:
            if parar():
                progresso.pausado = True
                break
            if not d.usar_ia:
                break  # sem IA (desligada, sem memória, falhas seguidas): o resto continua "revisar"
            aquecendo = not d.aquecido
            inicio = relogio()
            resultado = d.descrever_com_ia(linha)
            progresso.feitos += 1
            if resultado and not aquecendo:  # a 1ª chamada carrega o modelo: não entra na média
                progresso.tempos.append(relogio() - inicio)
                if len(progresso.tempos) == ARQUIVOS_PARA_MEDIR:
                    avisar("estimativa")
            if resultado:
                texto, origem, revisar = resultado
                indice.gravar_descricao(linha["id"], texto, origem, revisar, _agora())
                progresso.por_ia += origem == "ia"
                progresso.por_visao += origem == "ia_visao"
                progresso.revisar -= 1
                dormir(cfg.pausa_entre_arquivos)
            if progresso.feitos % cfg.tamanho_lote == 0:
                indice.confirmar()
                progresso.lotes_gravados += 1
                avisar("lote")
                d.conferir_memoria()
    finally:
        indice.confirmar()
        d.terminar()
    progresso.lotes_gravados += 1
    progresso.terminou = not progresso.pausado
    avisar("fim")
    return progresso


def descrever_arquivo(
    indice: Indice,
    caminho: str | Path,
    cliente: ClienteIA | None,
    *,
    cfg: ConfigDescricao | None = None,
    memoria: Callable[[], int | None] = memoria_disponivel,
) -> ProgressoDescricao:
    """Descreve UM arquivo com a IA quando o usuário pede, mesmo que as regras já tenham resolvido."""
    cfg = cfg or ConfigDescricao()
    progresso = ProgressoDescricao(total=1)
    linha = indice.buscar(str(Path(caminho).resolve()))
    if linha is None:
        progresso.avisos.append("Este arquivo não está no índice. Rode `escanear` antes.")
        return progresso
    d = _Descritor(cliente, cfg, progresso, memoria)
    try:
        resultado = d.descrever_com_ia(linha)
    finally:
        d.terminar()
    if resultado is None:
        texto, origem, revisar = descricao_por_regras(linha), "regras", precisa_ia(linha)
        if linha["categoria"] == "imagem" and not d.modelo_visao and d.usar_ia:
            progresso.avisos.append("Imagens precisam de um modelo de visão, que não está instalado.")
    else:
        texto, origem, revisar = resultado
    indice.gravar_descricao(linha["id"], texto, origem, revisar, _agora())
    indice.confirmar()
    progresso.feitos = 1
    progresso.por_ia += origem == "ia"
    progresso.por_visao += origem == "ia_visao"
    progresso.por_regras += origem == "regras"
    progresso.revisar = int(revisar)
    progresso.terminou = True
    return progresso
