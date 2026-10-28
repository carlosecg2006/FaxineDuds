"""Mover para outra unidade (Fase 7B): ex.: do C: para o D:, arquivos ou pastas inteiras.

Entre unidades não dá para só renomear: é preciso copiar. Para nunca perder nada, cada arquivo:
  1. tem a intenção gravada no diário (operação `mover_unidade`, com o temporário e a quarentena);
  2. o original é RENOMEADO para a quarentena da unidade dele (mesma unidade: instantâneo).
     Se o arquivo estiver em uso, falha aqui e nada mudou;
  3. é copiado para um temporário oculto no destino, calculando o BLAKE3 enquanto lê;
  4. a cópia é lida de novo e o hash tem que bater (e bater com o índice, se já havia hash);
  5. só então o temporário ganha o nome final.
Qualquer erro ou Cancelar nos passos 3–5: o temporário (nosso) some e o original volta da quarentena.
O original fica na quarentena: o espaço da unidade de origem só é liberado ao esvaziar a quarentena.
Desfazer: o original volta e a cópia vai para a quarentena da unidade de destino (nunca é apagada).
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from blake3 import blake3

from . import config, disco
from .formato import formatar_bytes
from .hashes import BLOCO
from .quarentena import (
    ANTES_DE_MEXER,
    DEPOIS_DE_MEXER,
    Cancelado,
    OperacaoRecusada,
    Passo,
    Plano,
    Quarentena,
    mensagem_de_erro,
)
from .scanner import indexar_arquivo, so_na_nuvem

PREFIXO_TEMP = ".faxineiro-copiando-"
FOLGA = 512 * config.MB  # nunca encher o destino até a boca
ORIGINAL_NA_QUARENTENA = "original_na_quarentena"  # gancho dos testes: original já saiu, cópia nem começou
COPIADO = "copiado"  # gancho dos testes: cópia conferida, ainda com nome temporário

AVISO_PROGRAMAS = ("Programas podem perder o caminho destes arquivos (como aconteceu com os samples do "
                   "FL Studio): projetos, bibliotecas e atalhos que apontam para o lugar antigo vão dizer "
                   "\"arquivo não encontrado\". Se acontecer, dá para desfazer pela tela Quarentena.")


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _espaco_livre(pasta: Path) -> int:
    return shutil.disk_usage(Path(pasta).anchor).free


def _nome_livre(destino: Path, reservados: set[Path]) -> tuple[Path, bool]:
    """Nunca sobrescreve: 'x.wav' → 'x (2).wav'; pasta 'Samples' → 'Samples (2)'."""
    if not disco.existe(destino) and destino not in reservados:
        return destino, False
    n = 2
    while True:
        candidato = destino.with_name(f"{destino.stem} ({n}){destino.suffix}" if destino.suffix
                                      else f"{destino.name} ({n})")
        if not disco.existe(candidato) and candidato not in reservados:
            return candidato, True
        n += 1


# --- prévia --------------------------------------------------------------------------


def _problema_da_pasta(q: Quarentena, pasta: Path) -> tuple[list[Path], list[Path], str | None]:
    """Arquivos e subpastas de uma pasta inteira; ou o motivo para não mover a pasta.
    A pasta vai INTEIRA ou não vai: pasta-bloco, bloqueada, nuvem ou link dentro → recusa tudo."""
    area = q._area(pasta)
    protecoes = q.protecoes_da_area(area)
    if pasta in q.areas:
        return [], [], "é uma área inteira (C:\\Users\\..., D:\\): escolha pastas de dentro"
    if protecoes.bloqueios.bloqueada(pasta):
        return [], [], "pasta bloqueada (regra 3): não mexo"
    if protecoes.nuvem(pasta / "x"):
        return [], [], "pasta sincronizada com a nuvem: não mexo"
    arquivos: list[Path] = []
    pastas: list[Path] = [pasta]
    for raiz, subpastas, nomes in disco.percorrer(pasta):
        raiz = Path(raiz)
        if os.path.islink(disco.no_disco(raiz)) or os.path.isjunction(disco.no_disco(raiz)):
            return [], [], f"tem um atalho de pasta (link/junção) dentro: {raiz.name}"
        if protecoes.bloqueios.bloqueada(raiz):
            return [], [], f"tem uma pasta bloqueada dentro ({raiz.name})"
        motivo = protecoes.motivo_bloco(raiz)
        if motivo:
            return [], [], f"é (ou tem dentro) uma pasta-bloco: {raiz.name} — {motivo}"
        for s in subpastas:
            pastas.append(raiz / s)
        for n in nomes:
            arquivo = raiz / n
            if os.path.islink(disco.no_disco(arquivo)):
                return [], [], f"tem um atalho (link) dentro: {n}"
            if so_na_nuvem(disco.info(arquivo)):
                return [], [], f"tem arquivo que está só na nuvem dentro: {n}"
            arquivos.append(arquivo)
    return arquivos, pastas, None


def _pastas_esvaziadas(pastas: list[Path], arquivos: list[Path]) -> list[Path]:
    """Das pastas da origem, as que a mudança esvazia (tinham pelo menos um arquivo na árvore).
    Pastas que já estavam vazias ficam onde estão — e, com elas, as de cima. Mais funda primeiro."""
    com_arquivo = {a.parent for a in arquivos}
    vazias_antes = set()
    for p in sorted(pastas, key=lambda p: -len(p.parts)):
        filhas = [f for f in pastas if f.parent == p]
        if p not in com_arquivo and not filhas:
            vazias_antes.add(p)
        elif any(f in vazias_antes for f in filhas):
            vazias_antes.add(p)  # fica uma pasta vazia lá dentro: a de cima também fica
    return sorted((p for p in pastas if p not in vazias_antes), key=lambda p: -len(p.parts))


def planejar_mover_unidade(
    q: Quarentena,
    itens: Iterable[str | Path],
    pasta_destino: str | Path,
    *,
    espaco_livre: Callable[[Path], int] = _espaco_livre,
    folga: int = FOLGA,
) -> Plano:
    """Prévia de mover arquivos e/ou pastas inteiras para `pasta_destino` (em OUTRA unidade).
    Nada muda no disco aqui."""
    destino_base = Path(pasta_destino).resolve()
    plano = Plano("mover_unidade", f"mover para {destino_base}")
    area_destino = q._area(destino_base)
    if area_destino is None:
        problema_destino = q._fora_da_area(destino_base)
    elif not disco.eh_pasta(destino_base):
        problema_destino = "a pasta de destino não existe"
    else:
        protecoes = q.protecoes_da_area(area_destino)
        problema_destino = protecoes.motivo_para_nao_mexer(destino_base / "x", area_destino)
        if problema_destino is None and destino_base != area_destino and protecoes.bloqueios.bloqueada(destino_base):
            problema_destino = "destino é uma pasta bloqueada"
        if problema_destino is None and destino_base != area_destino and protecoes.motivo_bloco(destino_base):
            problema_destino = f"destino é uma pasta-bloco ({destino_base.name})"
        if problema_destino:
            problema_destino = "destino: " + problema_destino

    reservados: set[Path] = set()
    vazias = 0
    for item in itens:
        origem = Path(item).resolve()
        passo_item = Passo(origem=origem, destino=None, tamanho=0, pasta_raiz=str(area_destino))
        if not disco.existe(origem):
            passo_item.problema = "não encontrado"
        elif problema_destino:
            passo_item.problema = problema_destino
        elif q._mesma_unidade(origem, destino_base):
            passo_item.problema = "destino na mesma unidade: aqui é só mover a pasta (use Organizar ou o Windows)"
        elif motivo := q.motivo_proibido(origem):
            passo_item.problema = motivo
        if passo_item.problema:
            plano.passos.append(passo_item)
            continue

        topo, _ = _nome_livre(destino_base / origem.name, reservados)
        reservados.add(topo)
        if disco.eh_arquivo(origem):
            linha = q.indice.buscar(str(origem))
            plano.passos.append(Passo(origem=origem, destino=topo, tamanho=disco.tamanho(origem),
                                      hash_esperado=linha["hash_completo"] if linha else None,
                                      pasta_raiz=str(area_destino), renomeado=topo.name != origem.name))
            continue
        arquivos, pastas, motivo = _problema_da_pasta(q, origem)
        if motivo:
            passo_item.problema = motivo
            plano.passos.append(passo_item)
            continue
        for arquivo in arquivos:
            linha = q.indice.buscar(str(arquivo))
            plano.passos.append(Passo(origem=arquivo, destino=topo / arquivo.relative_to(origem),
                                      tamanho=disco.tamanho(arquivo),
                                      hash_esperado=linha["hash_completo"] if linha else None,
                                      pasta_raiz=str(area_destino), renomeado=topo.name != origem.name))
        esvaziadas = _pastas_esvaziadas(pastas, arquivos)
        vazias += len(pastas) - len(esvaziadas)
        for pasta in esvaziadas:
            plano.passos.append(Passo(origem=pasta, destino=None, tamanho=0, remover_pasta=True))

    _conferir_espaco(q, plano, destino_base, espaco_livre, folga)
    if plano.validos:
        for unidade in sorted({q.unidade(p.origem) for p in plano.validos if not p.remover_pasta}):
            local = q.local(next(p.origem for p in plano.validos if q.unidade(p.origem) == unidade))
            plano.avisos.append(f"O espaço do {unidade} só é liberado quando você ESVAZIAR a quarentena "
                                f"({local}). Até lá, os arquivos ocupam espaço nas duas unidades.")
        plano.avisos.append(AVISO_PROGRAMAS)
        if vazias:
            plano.avisos.append(f"{vazias} pasta(s) vazia(s) não são copiadas e ficam na origem.")
    return plano


def _conferir_espaco(q: Quarentena, plano: Plano, destino: Path, espaco_livre: Callable[[Path], int], folga: int) -> None:
    precisa = sum(p.tamanho for p in plano.validos)
    if not precisa:
        return
    livre = espaco_livre(destino)
    texto = (f"Espaço no {q.unidade(destino)} — precisa de {formatar_bytes(precisa)}, livre "
             f"{formatar_bytes(livre)} (deixo {formatar_bytes(folga)} de folga).")
    if precisa + folga > livre:
        for p in plano.validos:
            p.problema = f"sem espaço no destino ({formatar_bytes(precisa)} para {formatar_bytes(livre)} livres)"
        texto = "NÃO CABE. " + texto
    plano.avisos.insert(0, texto)


# --- executar ------------------------------------------------------------------------


def copiar_conferindo(
    origem: Path,
    temporario: Path,
    parar: Callable[[], bool] = lambda: False,
    ao_copiar: Callable[[int], None] | None = None,
) -> str:
    """Copia em blocos de 1 MB calculando o BLAKE3 do que leu. Nunca sobrescreve ("xb").
    `parar()` entre um bloco e outro: levanta Cancelado (quem chamou desfaz)."""
    h = blake3()
    copiados = 0
    with disco.abrir(origem) as f, disco.abrir(temporario, "xb") as g:
        while bloco := f.read(BLOCO):
            if parar():
                raise Cancelado()
            h.update(bloco)
            g.write(bloco)
            copiados += len(bloco)
            if ao_copiar:
                ao_copiar(copiados)
        g.flush()
        os.fsync(g.fileno())  # a cópia está mesmo no disco antes de dar o nome final
    return h.hexdigest()


def _apagar_temporario(temporario: Path | None) -> None:
    """Remove só a cópia PARCIAL que o próprio app criou (nunca um arquivo do usuário)."""
    if temporario and temporario.name.startswith(PREFIXO_TEMP) and disco.existe(temporario):
        os.remove(disco.no_disco(temporario))


def _voltar_original(q: Quarentena, op_id: int, origem: Path, na_quarentena: Path, temporario: Path,
                     motivo: str) -> None:
    """Desfaz um passo que não terminou: some a cópia parcial e o original volta para o lugar."""
    _apagar_temporario(temporario)
    try:
        if disco.existe(na_quarentena) and not disco.existe(origem):
            disco.renomear(na_quarentena, origem)
        q.indice.concluir_operacao(op_id, "falhou", _agora(), f"{motivo}; nada mudou")
    except OSError as erro:
        q.indice.concluir_operacao(op_id, "falhou", _agora(),
                                   f"{motivo}; ATENÇÃO: o original ficou em {na_quarentena} ({mensagem_de_erro(erro)})")
    q.indice.confirmar()


def executar_passo(q: Quarentena, passo: Passo, lote_id: int, parar: Callable[[], bool] = lambda: False) -> None:
    origem, destino = passo.origem, passo.destino
    assert destino is not None
    q._conferir_limite(origem, destino)
    if q._mesma_unidade(origem, destino):
        raise OperacaoRecusada("destino na mesma unidade")
    if disco.existe(destino):
        raise OperacaoRecusada(f"já existe {destino}; não sobrescrevo")
    na_quarentena = q._destino_na_quarentena(origem, lote_id)
    if not q._mesma_unidade(origem, na_quarentena):
        raise OperacaoRecusada("a quarentena fica em outra unidade (não copio arquivos)")
    if disco.existe(na_quarentena):
        raise OperacaoRecusada(f"já existe algo na quarentena: {na_quarentena}")
    temporario = destino.with_name(f"{PREFIXO_TEMP}{uuid.uuid4().hex[:8]}{destino.suffix}")

    criadas = q.pastas_que_faltam(destino.parent)
    disco.criar_pastas(destino.parent)
    disco.criar_pastas(na_quarentena.parent)
    op_id = q.indice.registrar_operacao(
        lote_id=lote_id, tipo="mover_unidade", origem=str(origem), destino=str(destino),
        pasta_raiz=passo.pasta_raiz, tamanho=passo.tamanho, hash_completo=passo.hash_esperado,
        ref_operacao=None, agora=_agora(), pastas_criadas=json.dumps(criadas),
        temporario=str(temporario), quarentena=str(na_quarentena),
    )
    q.gancho(ANTES_DE_MEXER, passo)
    q._no_disco(op_id, lambda: disco.renomear(origem, na_quarentena))  # em uso → falha aqui, nada mudou
    q.gancho(ORIGINAL_NA_QUARENTENA, passo)
    try:
        h = copiar_conferindo(na_quarentena, temporario, parar, q.ao_copiar)
        if passo.hash_esperado and h != passo.hash_esperado:
            raise OperacaoRecusada("o arquivo mudou desde a última análise; rode escanear e tente de novo")
        if q.hasher.completo(temporario) != h:
            raise OperacaoRecusada("a cópia no destino não bateu com o original (hash BLAKE3)")
        st = disco.info(na_quarentena)
        os.utime(disco.no_disco(temporario), ns=(st.st_atime_ns, st.st_mtime_ns))  # mantém a data
    except (Cancelado, KeyboardInterrupt):  # botão Cancelar ou Ctrl+C na linha de comando
        _voltar_original(q, op_id, origem, na_quarentena, temporario, "cancelado")
        raise
    except (OSError, OperacaoRecusada) as erro:
        _voltar_original(q, op_id, origem, na_quarentena, temporario, mensagem_de_erro(erro).removesuffix("; nada mudou"))
        raise
    q.gancho(COPIADO, passo)
    try:
        disco.renomear(temporario, destino)
    except OSError as erro:
        _voltar_original(q, op_id, origem, na_quarentena, temporario, mensagem_de_erro(erro).removesuffix("; nada mudou"))
        raise
    q.gancho(DEPOIS_DE_MEXER, passo)
    concluir_mover(q, op_id, h)


def concluir_mover(q: Quarentena, op_id: int, hash_completo: str) -> None:
    """Cópia no lugar e original na quarentena: registra o original como item da quarentena
    (aparece na tela, entra no Esvaziar e no desfazer) e atualiza o índice."""
    op = q.indice.operacao(op_id)
    origem, destino = op["origem"], Path(op["destino"])
    q.indice.gravar_hash_operacao(op_id, hash_completo)
    linha = q.indice.buscar(origem)
    raiz_origem = linha["pasta_raiz"] if linha else str(q._area(Path(origem)) or Path(origem).parent)
    if not any(l["tipo"] == "quarentena" for l in q.indice.operacoes_ligadas(op_id)):
        q.indice.registrar_operacao(
            lote_id=op["lote_id"], tipo="quarentena", origem=origem, destino=op["quarentena"],
            pasta_raiz=raiz_origem, tamanho=op["tamanho"], hash_completo=hash_completo, ref_operacao=op_id,
            agora=_agora(), estado="feita", situacao="na_quarentena",
        )
    q.indice.concluir_operacao(op_id, "feita", _agora(), situacao="movido")
    if linha is not None:
        q.indice.mudar_caminho(origem, str(destino), op["pasta_raiz"])  # mantém descrição e hashes
    else:
        indexar_arquivo(destino, q.indice, op["pasta_raiz"] or str(destino.parent))
    q.indice.confirmar()


def recuperar_mover(q: Quarentena, op) -> str:
    """O app fechou no meio de um "mover para outra unidade". Decide pelo que está no disco."""
    origem, destino = Path(op["origem"]), Path(op["destino"])
    na_quarentena = Path(op["quarentena"])
    temporario = Path(op["temporario"]) if op["temporario"] else None
    tem_origem, tem_destino, tem_q = disco.existe(origem), disco.existe(destino), disco.existe(na_quarentena)
    if tem_destino and tem_q and not tem_origem:
        h = q.hasher.completo(na_quarentena)
        if q.hasher.completo(destino) == h:
            concluir_mover(q, op["id"], h)
            return f"Concluída (mover para outra unidade, hash conferido): {origem} → {destino}"
        q.indice.concluir_operacao(op["id"], "falhou", _agora(),
                                   "verificar à mão: a cópia e o original (na quarentena) são diferentes")
        return f"ATENÇÃO, verificar à mão (cópia diferente do original): {destino} / {na_quarentena}"
    if not tem_destino:
        _apagar_temporario(temporario)
        if tem_q and not tem_origem:
            disco.renomear(na_quarentena, origem)
        if disco.existe(origem):
            q.indice.concluir_operacao(op["id"], "falhou", _agora(), "interrompida; nada mudou")
            return f"Interrompida, nada mudou (o original está no lugar): {origem}"
    q.indice.concluir_operacao(op["id"], "falhou", _agora(), "verificar à mão")
    return f"ATENÇÃO, verificar à mão: {origem} / {destino} / {na_quarentena}"
