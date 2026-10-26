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


def pasta_por_regras(linha: sqlite3.Row) -> str:
    """Sem IA: <Categoria>/<ano da modificação>, ex.: Imagens/2026."""
    ano = (linha["modificado_em"] or "")[:4] or "sem_data"
    return f"{PASTA_POR_CATEGORIA.get(linha['categoria'], 'Outros')}/{ano}"


def montar_prompt_pasta(linha: sqlite3.Row, ja_usadas: list[str]) -> str:
    usadas = ", ".join(ja_usadas[:30]) if ja_usadas else "(nenhuma ainda)"
    return "\n".join([
        "Você organiza os arquivos de um computador pessoal em pastas.",
        f"Escolha UMA pasta para o arquivo abaixo, com no máximo {MAX_NIVEIS} níveis "
        '(exemplos: "Documentos/Faculdade", "Imagens/Viagens", "Finanças/Boletos").',
        "Reutilize uma das pastas já usadas quando fizer sentido. Use nomes curtos em português.",
        'Responda SOMENTE em JSON, assim: {"pasta": "Categoria/Subcategoria"}',
        "",
        f"Pastas já usadas: {usadas}",
        f"Arquivo: {linha['nome']}",
        f"Descrição: {linha['descricao'] or '(sem descrição)'}",
        f"Tipo: {linha['tipo_real']} ({linha['categoria']})",
        f"Modificado em: {(linha['modificado_em'] or '')[:10]}",
    ])


def _ler_json_pasta(resposta: str) -> str | None:
    try:
        dados = json.loads(resposta)
    except ValueError:
        achado = re.search(r'"pasta"\s*:\s*"([^"]+)"', resposta)
        return achado.group(1) if achado else None
    return dados.get("pasta") if isinstance(dados, dict) else None


@dataclass
class ResultadoSugestao:
    sugeridos: int = 0
    por_ia: int = 0
    por_regras: int = 0
    sem_descricao: int = 0
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
) -> ResultadoSugestao:
    """Guarda em `pasta_sugerida` a pasta que cada arquivo deveria ter (relativa à `pasta`)."""
    r = ResultadoSugestao()
    linhas = [l for l in indice.todos(prefixo_da_pasta(pasta)) if refazer or l["pasta_sugerida"] is None]
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
                                         formato_json=True, max_tokens=40)
                sugestao = sanear_pasta(_ler_json_pasta(resposta))
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


def planejar_organizacao(indice: Indice, pasta: str | Path, quarentena: Quarentena) -> Plano:
    """Plano (prévia) de mover cada arquivo para `pasta/<pasta_sugerida>/<nome>`."""
    base = Path(pasta).resolve()
    movimentos = []
    for linha in indice.todos(prefixo_da_pasta(base)):
        if not linha["pasta_sugerida"]:
            continue
        origem = Path(linha["caminho"])
        destino = base.joinpath(*linha["pasta_sugerida"].split("/")) / origem.name
        if origem.parent == destino.parent:
            continue  # já está na pasta sugerida
        movimentos.append((origem, destino))
    return quarentena.planejar_organizar(movimentos, f"organizar {base.name} ({datetime.now():%d/%m %H:%M})")
