"""Sugere uma pasta para cada arquivo (IA local ou regras) e monta o plano de movimentos.

A sugestão é só sugestão: aplicar passa pela prévia e pelo executor da Fase 3
(diário de operações + desfazer).
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .descricoes import ClienteIA
from .ia import IAIndisponivel, avaliar_ia
from .indice import Indice
from .memoria import memoria_disponivel
from .protecoes import Protecoes
from .quarentena import Plano, Quarentena
from .raiox import prefixo_da_pasta

MAX_NIVEIS = 2
MAX_NOME_PASTA = 40
_PROIBIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVADOS = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}

PASTA_POR_CATEGORIA = {
    "imagem": "Imagens", "documento": "Documentos", "texto": "Textos", "audio": "Áudios",
    "video": "Vídeos", "compactado": "Compactados", "executavel": "Programas", "outro": "Outros",
}


def sanear_pasta(texto: str | None) -> str | None:
    """Transforma a resposta da IA num caminho relativo seguro de até 2 níveis, ou None."""
    if not texto:
        return None
    partes = []
    for bruta in re.split(r"[\\/]+", texto.strip()):
        if re.fullmatch(r"\s*[A-Za-z]:\s*", bruta):  # "C:" — nada de unidade
            continue
        parte = _PROIBIDOS.sub("", bruta).strip().rstrip(". ")
        if not parte or parte in (".", "..") or parte.upper() in _RESERVADOS:
            continue
        partes.append(parte[:MAX_NOME_PASTA].rstrip(". "))
        if len(partes) == MAX_NIVEIS:
            break
    return "/".join(partes) or None


def pasta_principal(linha: sqlite3.Row) -> str:
    """O 1º nível vem SEMPRE das regras, pelo tipo real (onde as regras não erram)."""
    return PASTA_POR_CATEGORIA.get(linha["categoria"], "Outros")


def pasta_por_regras(linha: sqlite3.Row) -> str:
    """Sem IA: <Categoria>/<ano da modificação>, ex.: Imagens/2026."""
    ano = (linha["modificado_em"] or "")[:4] or "sem_data"
    return f"{pasta_principal(linha)}/{ano}"


# Assuntos que não ajudam a agrupar (ou que só repetem a categoria).
_ASSUNTOS_INUTEIS = {
    "arquivo", "arquivos", "documento", "documentos", "geral", "outros", "diversos", "misc", "pasta",
    "categoria", "subcategoria", "assunto", "texto", "textos", "imagem", "imagens", "foto", "fotos",
    "video", "vídeo", "videos", "vídeos", "audio", "áudio", "audios", "áudios", "programa", "programas",
    "compactado", "compactados", "pessoal computador",
}


_PALAVRAS_DE_LIGACAO = {"de", "da", "do", "das", "dos", "e", "em", "um", "uma", "sua", "seu", "para", "com", "a", "o"}


def sanear_assunto(texto: str | None) -> str | None:
    """Um nome de pasta só (1 nível), curto e útil; None se não servir."""
    caminho = sanear_pasta(texto)
    if not caminho:
        return None
    assunto = caminho.split("/")[-1]
    # "Imagens - Viagens" → "Viagens"; "Reunião de TCC - Novo Documento" → "Reunião de TCC"
    pedacos = [p.strip() for p in assunto.split(" - ") if p.strip().casefold() not in _ASSUNTOS_INUTEIS]
    if not pedacos:
        return None
    palavras = pedacos[0].split()[:3]  # no máximo 3 palavras
    while palavras and palavras[-1].casefold() in _PALAVRAS_DE_LIGACAO:  # "Dados de uma" → "Dados"
        palavras.pop()
    if not palavras or palavras[0].casefold() in ("arquivo", "arquivos", "modificação", "novo", "nova"):
        return None  # "Arquivos de texto", "Novo Arquivo": não diz o assunto
    assunto = " ".join(palavras)[:30].strip()
    if assunto.casefold() in _ASSUNTOS_INUTEIS or len(assunto) < 3 or assunto.isdigit():
        return None
    return assunto[0].upper() + assunto[1:]


def montar_prompt_pasta(linha: sqlite3.Row, ja_usadas: list[str]) -> str:
    """A IA só escolhe o ASSUNTO (2º nível). Modelos pequenos erram menos com uma pergunta menor.

    Sem lista de assuntos já usados: no teste real, o 0.5b copiava a lista em vez de pensar.
    A coerência vem depois, juntando assuntos iguais (ver `_unificar`)."""
    principal = pasta_principal(linha)
    return "\n".join([
        "Você organiza arquivos de um computador pessoal.",
        f"Este arquivo vai para a pasta '{principal}'. Dê um ASSUNTO curto (1 ou 2 palavras, em português)",
        "para a subpasta, de acordo com o conteúdo descrito. Não repita o tipo do arquivo.",
        'Exemplos de assuntos: "Faculdade", "Finanças", "Receitas", "Trabalho", "Casa".',
        'Responda SOMENTE em JSON: {"assunto": "..."}',
        "",
        f"Arquivo: {linha['nome']}",
        f"Descrição: {linha['descricao'] or '(sem descrição)'}",
    ])


def _ler_json_pasta(resposta: str) -> str | None:
    try:
        dados = json.loads(resposta)
    except ValueError:
        achado = re.search(r'"(?:assunto|pasta)"\s*:\s*"([^"]+)"', resposta)
        return achado.group(1) if achado else None
    if not isinstance(dados, dict):
        return None
    return dados.get("assunto") or dados.get("pasta")


def _unificar(sugestao: str, ja_usadas: list[str]) -> str:
    """'Documentos/finanças' e 'Documentos/Finanças' viram a mesma pasta (a que já existia)."""
    for existente in ja_usadas:
        if existente.casefold() == sugestao.casefold():
            return existente
    return sugestao


@dataclass
class ResultadoSugestao:
    sugeridos: int = 0
    por_ia: int = 0
    por_regras: int = 0
    sem_descricao: int = 0
    protegidos: int = 0  # nuvem, pasta-bloco ou bloqueada: nem recebem sugestão
    pausado: bool = False
    avisos: list[str] = field(default_factory=list)


def sugerir_pastas(
    indice: Indice,
    pasta: str | Path,
    cliente: ClienteIA | None,
    *,
    refazer: bool = False,
    timeout: float = 60,
    max_falhas_seguidas: int = 3,
    parar: Callable[[], bool] = lambda: False,
    memoria: Callable[[], int | None] = memoria_disponivel,
    protecoes: Protecoes | None = None,
) -> ResultadoSugestao:
    """Guarda em `pasta_sugerida` a pasta que cada arquivo deveria ter (relativa à `pasta`).

    Arquivos protegidos (pasta da nuvem, pasta-bloco, bloqueada) nem recebem sugestão.
    """
    r = ResultadoSugestao()
    base = Path(pasta).resolve()
    protecoes = protecoes or Protecoes()
    linhas = []
    for l in indice.todos(prefixo_da_pasta(base)):
        if protecoes.motivo_para_nao_organizar(Path(l["caminho"]), base):
            r.protegidos += 1
        elif refazer or l["pasta_sugerida"] is None:
            linhas.append(l)
    if not linhas:
        return r
    _, usar_ia, aviso = avaliar_ia(cliente, memoria)
    if not usar_ia:
        r.avisos.append((aviso or "IA indisponível.") + " Sugestões por regras simples (tipo e ano); revise antes de aplicar.")
    usou_ia = False
    ja_usadas = sorted({l["pasta_sugerida"] for l in indice.todos(prefixo_da_pasta(pasta)) if l["pasta_sugerida"]})
    falhas = 0

    for linha in linhas:
        if parar():
            r.pausado = True
            break
        sugestao = None
        if linha["descricao"] is None:
            r.sem_descricao += 1
        if usar_ia:
            try:
                resposta = cliente.gerar(montar_prompt_pasta(linha, ja_usadas), timeout=timeout,
                                         formato_json=True, max_tokens=30)
                assunto = sanear_assunto(_ler_json_pasta(resposta))
                sugestao = _unificar(f"{pasta_principal(linha)}/{assunto}", ja_usadas) if assunto else None
                falhas = 0
                usou_ia = True
            except IAIndisponivel as erro:
                falhas += 1
                r.avisos.append(f"IA falhou em {linha['nome']}: {erro}")
                if falhas >= max_falhas_seguidas:
                    usar_ia = False
                    r.avisos.append("Falhas seguidas: o resto vai por regras simples.")
        if sugestao:
            r.por_ia += 1
        else:
            sugestao = pasta_por_regras(linha)
            r.por_regras += 1
        if sugestao not in ja_usadas:
            ja_usadas.append(sugestao)
        indice.gravar_pasta_sugerida(linha["id"], sugestao)
        r.sugeridos += 1
    indice.confirmar()
    if usou_ia and hasattr(cliente, "descarregar"):
        cliente.descarregar()  # libera a memória do modelo logo
    return r


def planejar_organizacao(
    indice: Indice, pasta: str | Path, quarentena: Quarentena, protecoes: Protecoes | None = None
) -> Plano:
    """Plano (prévia) de mover cada arquivo SOLTO para `pasta/<pasta_sugerida>/<nome>`.

    Fica de fora (e aparece em `plano.ignorados` com o motivo): pasta bloqueada, pasta da
    nuvem (mover para fora apagaria da nuvem) e tudo dentro de pastas-bloco (projetos, programas,
    jogos), que são tratadas como uma unidade.
    """
    base = Path(pasta).resolve()
    protecoes = protecoes or Protecoes()
    movimentos = []
    ignorados: list[tuple[Path, str]] = []
    for linha in indice.todos(prefixo_da_pasta(base)):
        origem = Path(linha["caminho"])
        motivo = protecoes.motivo_para_nao_organizar(origem, base)
        if motivo:
            ignorados.append((origem, motivo))
            continue
        if not linha["pasta_sugerida"]:
            continue
        destino = base.joinpath(*linha["pasta_sugerida"].split("/")) / origem.name
        if origem.parent == destino.parent:
            continue  # já está na pasta sugerida
        motivo_destino = protecoes.destino_proibido(destino, base) or (
            # não colocar arquivos soltos DENTRO de um projeto/jogo existente
            protecoes.bloco_que_contem(destino, base) and "destino dentro de pasta-bloco")
        if motivo_destino:
            ignorados.append((origem, motivo_destino))
            continue
        movimentos.append((origem, destino))
    plano = quarentena.planejar_organizar(movimentos, f"organizar {base.name} ({datetime.now():%d/%m %H:%M})")
    plano.ignorados = ignorados
    return plano
