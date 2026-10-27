"""Quarentena com diário de operações, recuperação após travamento e desfazer.

Toda operação tem duas etapas:
  1. planejar_*()  → devolve um Plano (a prévia / dry-run). Nada no disco muda.
  2. executar(plano) → executa, gravando cada passo no diário ANTES de mexer no disco.

"Excluir" nunca apaga: move (renomeia) para a `_quarentena` da mesma unidade.
A única operação que apaga de vez é esvaziar a quarentena (exceção da regra 1).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import disco, raiox
from .config import NOME_QUARENTENA, PASTA_TESTE, area_de, pasta_quarentena
from .hashes import Hasher
from .indice import Indice
from .protecoes import Protecoes, fora_da_area, protecoes_para
from .scanner import indexar_arquivo

# Ganchos usados pelos testes para simular travamento em pontos críticos.
ANTES_DE_MEXER = "antes_de_mexer"  # diário já gravado, disco ainda intacto
DEPOIS_DE_MEXER = "depois_de_mexer"  # disco já mudou, diário ainda diz "em andamento"


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Passo:
    origem: Path
    destino: Path | None  # quarentena: definido na execução (depende do número do lote)
    tamanho: int
    hash_esperado: str | None = None
    pasta_raiz: str | None = None
    ref_operacao: int | None = None  # restaurar/esvaziar: a operação de quarentena original
    manter: Path | None = None  # duplicados: a cópia que fica (precisa existir e ser igual)
    problema: str | None = None  # se preenchido, o passo não será executado
    renomeado: bool = False  # restaurar com outro nome por causa de conflito
    recriar_pasta: bool = False  # desfazer de "remover_pasta": só recria a pasta vazia
    remover_pasta: bool = False  # mover de unidade: pasta de origem que a mudança esvaziou
    quarentenar_copia: bool = False  # desfazer de "mover_unidade": a cópia no destino vai para a quarentena


@dataclass
class Plano:
    tipo: str  # quarentena | restaurar | esvaziar | organizar
    descricao: str
    passos: list[Passo] = field(default_factory=list)
    ignorados: list[tuple[Path, str]] = field(default_factory=list)  # (arquivo, motivo) que nem entraram
    avisos: list[str] = field(default_factory=list)  # mostrados na prévia (ex.: espaço, programas)

    @property
    def validos(self) -> list[Passo]:
        return [p for p in self.passos if p.problema is None]

    @property
    def total_bytes(self) -> int:
        return sum(p.tamanho for p in self.validos)


@dataclass
class Resultado:
    lote_id: int | None = None
    feitos: list[Passo] = field(default_factory=list)
    falhas: list[tuple[Passo, str]] = field(default_factory=list)
    cancelado: bool = False


class OperacaoRecusada(Exception):
    pass


class Cancelado(Exception):
    """O usuário cancelou no meio de uma cópia longa (mover de unidade): já foi desfeito."""


def mensagem_de_erro(erro: Exception) -> str:
    """Traduz os erros mais comuns do Windows para algo que o usuário entenda."""
    if isinstance(erro, OSError):
        codigo = getattr(erro, "winerror", None)
        if codigo in (32, 33):
            return "arquivo em uso por outro programa (feche-o e tente de novo); nada mudou"
        if codigo == 5 or isinstance(erro, PermissionError):
            return "sem permissão para mexer neste arquivo; nada mudou"
        if codigo == 206:
            return "caminho longo demais para o Windows (mais de 260 caracteres); nada mudou"
        return f"{erro.strerror or erro}; nada mudou"
    return str(erro)


class Quarentena:
    def __init__(
        self,
        indice: Indice,
        *,
        limite: Path | tuple[Path, ...] | list[Path] = PASTA_TESTE,
        local: Callable[[Path], Path] | None = None,
        hasher: Hasher | None = None,
        gancho: Callable[[str, Passo], None] | None = None,
        protecoes: Protecoes | None = None,
        unidade: Callable[[Path], str] | None = None,
    ) -> None:
        """`limite`: a área (ou as áreas) onde é permitido mudar o disco — trava da regra 5.
        No modo PC real são `config.areas_de_acao(True)`; desligado, só a pasta_teste.
        `local`: diz onde fica a quarentena de cada arquivo (padrão: config.pasta_quarentena).
        `protecoes`: força uma Protecoes (testes); o padrão escolhe pela área.
        `unidade`: diz em que unidade está um caminho (padrão: a letra; os testes simulam duas)."""
        self.indice = indice
        areas = (limite,) if isinstance(limite, (str, Path)) else tuple(limite)
        self.areas = tuple(Path(a).resolve() for a in areas)
        self.limite = self.areas[0]
        self.local = local or (lambda arq: pasta_quarentena(arq))
        self.hasher = hasher or Hasher()
        self.gancho = gancho or (lambda momento, passo: None)
        self._protecoes_fixas = protecoes
        self._protecoes: dict[Path, Protecoes] = {}
        self.ao_copiar: Callable[[int], None] | None = None  # mover de unidade: bytes copiados do arquivo atual
        self.unidade = unidade or (lambda c: Path(c).resolve().drive.upper())

    # --- travas -------------------------------------------------------------

    def _area(self, caminho: Path) -> Path | None:
        return area_de(caminho, self.areas)

    def _fora_da_area(self, caminho: Path) -> str:
        return fora_da_area(caminho, self.areas)

    def _conferir_limite(self, *caminhos: Path) -> None:
        for c in caminhos:
            if self._area(c) is None:
                raise OperacaoRecusada(f"{self._fora_da_area(c)}: {c}")

    def protecoes_da_area(self, area: Path) -> Protecoes:
        """Na pasta_teste (e nas pastas de teste), os bloqueios de sempre; no PC real, também a
        pasta do próprio app."""
        if self._protecoes_fixas is not None:
            return self._protecoes_fixas
        if area not in self._protecoes:
            self._protecoes[area] = protecoes_para(area)
        return self._protecoes[area]

    def motivo_proibido(self, caminho: Path) -> str | None:
        """None = esta ação pode mexer em `caminho`. Senão, o motivo (aparece na prévia).
        Fora das áreas, pasta bloqueada, nuvem, pasta-bloco e pasta de programa: nunca."""
        area = self._area(caminho)
        if area is None:
            return self._fora_da_area(caminho)
        return self.protecoes_da_area(area).motivo_para_nao_mexer(Path(caminho), area)

    def _em_pasta_bloqueada(self, caminho: Path) -> bool:
        """Regra 3: arquivo dentro de pasta bloqueada (FileHistory, AppData...) nunca entra em ação.
        Olha do arquivo até a área permitida (o que está acima dela não conta)."""
        area = self._area(caminho)
        if area is None:
            return False
        bloqueios = self.protecoes_da_area(area).bloqueios
        return any(bloqueios.bloqueada(p) for p in Path(caminho).parents if area in p.parents)

    def _mesma_unidade(self, a: Path, b: Path) -> bool:
        return self.unidade(a) == self.unidade(b)

    def _destino_na_quarentena(self, origem: Path, lote_id: int) -> Path:
        """_quarentena\\0003\\<caminho relativo>\\arquivo.ext — mantém as pastas e evita colisões.

        O caminho é relativo à pasta onde a quarentena mora (raiz da unidade em produção,
        pasta_teste em desenvolvimento), para não estourar o limite de 260 caracteres do Windows.
        """
        origem = origem.resolve()
        raiz_q = self.local(origem)
        try:
            relativo = origem.relative_to(raiz_q.parent)
        except ValueError:
            relativo = Path(*origem.parts[1:])
        return raiz_q / f"{lote_id:04d}" / relativo

    # --- recuperação após travamento -----------------------------------------

    def recuperar_diario(self) -> list[str]:
        """Termina ou marca como falha as operações que ficaram pela metade."""
        mensagens = []
        for op in self.indice.operacoes_em_andamento():
            origem, destino = Path(op["origem"]), Path(op["destino"])
            tem_origem, tem_destino = disco.existe(origem), disco.existe(destino)
            agora = _agora()

            if op["tipo"] == "mover_unidade":
                from .transferir import recuperar_mover  # import aqui: transferir usa esta classe
                mensagens.append(recuperar_mover(self, op))
            elif op["tipo"] in ("remover_pasta", "recriar_pasta"):
                alvo = origem if op["tipo"] == "remover_pasta" else destino
                pronto = not disco.existe(alvo) if op["tipo"] == "remover_pasta" else disco.eh_pasta(alvo)
                if pronto:
                    self.indice.concluir_operacao(op["id"], "feita", agora,
                                                  situacao="removida" if op["tipo"] == "remover_pasta" else None)
                    if op["tipo"] == "recriar_pasta" and op["ref_operacao"]:
                        self.indice.mudar_situacao(op["ref_operacao"], "restaurado")
                    mensagens.append(f"Concluída ({op['tipo']}): {alvo}")
                else:
                    self.indice.concluir_operacao(op["id"], "falhou", agora, "interrompida; nada mudou")
                    mensagens.append(f"Interrompida, nada mudou: {alvo}")
            elif op["tipo"] == "esvaziar":
                if not tem_origem:
                    self._concluir_esvaziar(op["id"], op["ref_operacao"], agora)
                    mensagens.append(f"Concluída (esvaziar): {origem}")
                else:
                    self.indice.concluir_operacao(op["id"], "falhou", agora, "interrompida; nada foi apagado")
                    mensagens.append(f"Interrompida, nada foi apagado: {origem}")
            elif tem_destino and not tem_origem:
                try:
                    if op["tipo"] == "quarentena":
                        self._concluir_quarentena(op["id"], origem, agora)
                    elif op["tipo"] == "organizar":
                        self._concluir_organizar(op["id"], origem, destino, op["pasta_raiz"], agora)
                    else:
                        self._concluir_restaurar(op, destino, agora)
                    mensagens.append(f"Concluída ({op['tipo']}): {origem} → {destino}")
                except OperacaoRecusada as erro:
                    mensagens.append(f"Concluída com aviso ({op['tipo']}): {destino}: {erro}")
            elif tem_origem and not tem_destino:
                self.indice.concluir_operacao(op["id"], "falhou", agora, "interrompida; nada mudou")
                mensagens.append(f"Interrompida, nada mudou: {origem}")
            else:
                situacao = "os dois existem" if tem_origem else "nenhum dos dois existe"
                self.indice.concluir_operacao(op["id"], "falhou", agora, f"verificar à mão: {situacao}")
                mensagens.append(f"ATENÇÃO, verificar à mão ({situacao}): {origem} / {destino}")
        self.indice.confirmar()
        return mensagens

    # --- planejar (prévia) ----------------------------------------------------

    def planejar_mover(self, caminhos: Iterable[str | Path], descricao: str = "excluir") -> Plano:
        plano = Plano("quarentena", descricao)
        vistos: set[Path] = set()
        for c in caminhos:
            origem = Path(c).resolve()
            if origem in vistos:
                continue
            vistos.add(origem)
            passo = Passo(origem=origem, destino=None, tamanho=0)
            linha = self.indice.buscar(str(origem))
            if linha is not None:
                passo.pasta_raiz = linha["pasta_raiz"]
                passo.hash_esperado = linha["hash_completo"]
            if not disco.eh_arquivo(origem):
                passo.problema = "arquivo não encontrado"
            elif motivo := self.motivo_proibido(origem):
                passo.problema = motivo
            elif not self._mesma_unidade(origem, self.local(origem)):
                passo.problema = "a quarentena fica em outra unidade (não copio arquivos)"
            else:
                passo.tamanho = disco.tamanho(origem)
            plano.passos.append(passo)
        return plano

    def planejar_duplicados(self, pasta: str | Path) -> Plano:
        """Para cada grupo do Raio-X, manda para a quarentena todos menos o sugerido."""
        r = raiox.encontrar_duplicados(self.indice, pasta, hasher=self.hasher)
        plano = Plano("quarentena", "duplicados do Raio-X")
        for grupo in r.grupos:
            manter = Path(grupo.manter["caminho"])
            outros = [a["caminho"] for a in grupo.arquivos if a["id"] != grupo.manter["id"]]
            for passo in self.planejar_mover(outros).passos:
                passo.hash_esperado = grupo.hash_completo
                passo.manter = manter
                plano.passos.append(passo)
        return plano

    def planejar_desfazer(
        self,
        *,
        item: int | None = None,
        lote: int | None = None,
        conflito: str | Callable[[Path], str] = "renomear",
    ) -> Plano:
        """Traz de volta da quarentena. Nunca sobrescreve: em conflito, renomeia ou pula.

        `conflito`: "renomear", "pular" ou uma função que recebe o caminho original e
        devolve "renomear" ou "pular" (a CLI usa isso para perguntar ao usuário).
        """
        if item is None and lote is None:
            raise ValueError("Informe item ou lote.")
        plano = Plano("restaurar", f"desfazer {'item ' + str(item) if item else 'lote ' + str(lote)}")
        reservados: set[Path] = set()
        ops = self._com_ligadas(self.indice.itens_desfaziveis(item=item, lote=lote))
        # Pastas removidas voltam primeiro, para os arquivos terem onde cair.
        for op in sorted(ops, key=lambda o: o["tipo"] != "remover_pasta"):
            if op["tipo"] == "remover_pasta":
                pasta = Path(op["origem"])
                passo = Passo(origem=pasta, destino=pasta, tamanho=0, ref_operacao=op["id"], recriar_pasta=True)
                if self._area(pasta) is None:
                    passo.problema = self._fora_da_area(pasta)
                plano.passos.append(passo)
                continue
            if op["tipo"] == "mover_unidade":
                plano.passos.append(self._passo_desfazer_mover(op))
                continue
            na_quarentena, original = Path(op["destino"]), Path(op["origem"])
            passo = Passo(
                origem=na_quarentena, destino=original, tamanho=op["tamanho"] or 0,
                hash_esperado=op["hash_completo"], pasta_raiz=op["pasta_raiz"], ref_operacao=op["id"],
            )
            if not disco.eh_arquivo(na_quarentena):
                passo.problema = ("não está mais na quarentena" if op["tipo"] == "quarentena"
                                  else "não está mais onde o organizar deixou")
            elif self._area(na_quarentena) is None or self._area(original) is None:
                passo.problema = self._fora_da_area(original)
            elif disco.existe(original) or original in reservados:
                escolha = conflito(original) if callable(conflito) else conflito
                if escolha == "renomear":
                    passo.destino = self._nome_livre(original, reservados)
                    passo.renomeado = True
                else:
                    passo.problema = "já existe um arquivo com esse nome no lugar original (pulado)"
            if passo.problema is None:
                reservados.add(passo.destino)
            plano.passos.append(passo)
        if any(p.quarentenar_copia and p.problema is None for p in plano.passos):
            plano.avisos.append("Desfazer \"mover para outra unidade\": o original volta para o lugar dele e a "
                                "cópia no destino vai para a quarentena da unidade de destino (nada é apagado).")
        return plano

    def _com_ligadas(self, ops: list) -> list:
        """Mover de unidade são 2 registros: a mudança (`mover_unidade`) e o original na quarentena
        (`quarentena`, com ref_operacao para a mudança). Desfazer um deles desfaz os dois."""
        por_id = {op["id"]: op for op in ops}
        for op in list(ops):
            ligadas = []
            if op["tipo"] == "mover_unidade":
                ligadas = self.indice.operacoes_ligadas(op["id"])
            elif op["tipo"] == "quarentena" and op["ref_operacao"]:
                ref = self.indice.operacao(op["ref_operacao"])
                ligadas = [ref] if ref is not None and ref["tipo"] == "mover_unidade" else []
            for l in ligadas:
                desfazivel = ((l["tipo"] == "quarentena" and l["situacao"] == "na_quarentena")
                              or (l["tipo"] == "mover_unidade" and l["situacao"] == "movido"))
                if desfazivel and l["id"] not in por_id:
                    por_id[l["id"]] = l
        return sorted(por_id.values(), key=lambda o: o["id"])

    def _passo_desfazer_mover(self, op) -> Passo:
        """A cópia que o "mover para outra unidade" criou vai para a quarentena da unidade dela."""
        copia = Path(op["destino"])
        passo = Passo(origem=copia, destino=None, tamanho=op["tamanho"] or 0, ref_operacao=op["id"],
                      pasta_raiz=op["pasta_raiz"], quarentenar_copia=True)
        originais = [o for o in self.indice.operacoes_ligadas(op["id"]) if o["tipo"] == "quarentena"]
        if not any(o["situacao"] == "na_quarentena" for o in originais):
            passo.problema = "o original já saiu da quarentena (esvaziada?): a cópia fica onde está"
        elif not disco.eh_arquivo(copia):
            passo.problema = "a cópia não está mais no destino (nada a mandar para a quarentena)"
        elif self._area(copia) is None:
            passo.problema = self._fora_da_area(copia)
        return passo

    @staticmethod
    def _nome_livre(original: Path, reservados: set[Path], palavra: str = "restaurado") -> Path:
        n = 1
        while True:
            if palavra:
                sufixo = f" ({palavra})" if n == 1 else f" ({palavra} {n})"
            else:
                sufixo = f" ({n + 1})"
            candidato = original.with_name(f"{original.stem}{sufixo}{original.suffix}")
            if not disco.existe(candidato) and candidato not in reservados:
                return candidato
            n += 1

    def planejar_organizar(self, movimentos: Iterable[tuple[str | Path, str | Path]],
                           descricao: str = "organizar") -> Plano:
        """Mover arquivos para as pastas sugeridas. Nunca sobrescreve: conflito vira 'nome (2).ext'."""
        plano = Plano("organizar", descricao)
        reservados: set[Path] = set()
        for o, d in movimentos:
            origem, destino = Path(o).resolve(), Path(d).resolve()
            passo = Passo(origem=origem, destino=destino, tamanho=0)
            linha = self.indice.buscar(str(origem))
            if linha is not None:
                passo.pasta_raiz = linha["pasta_raiz"]
                passo.hash_esperado = linha["hash_completo"]
            if not disco.eh_arquivo(origem):
                passo.problema = "arquivo não encontrado"
            elif self._area(origem) is None or self._area(destino) is None:
                passo.problema = self._fora_da_area(origem if self._area(origem) is None else destino)
            elif self._em_pasta_bloqueada(origem) or self._em_pasta_bloqueada(destino):
                passo.problema = "dentro de pasta bloqueada (regra 3): não mexo"
            elif not self._mesma_unidade(origem, destino):
                passo.problema = "destino em outra unidade (não copio arquivos)"
            elif origem == destino:
                passo.problema = "já está no lugar sugerido"
            else:
                passo.tamanho = disco.tamanho(origem)
                if disco.existe(destino) or destino in reservados:
                    passo.destino = self._nome_livre(destino, reservados, palavra="")
                    passo.renomeado = True
                reservados.add(passo.destino)
            plano.passos.append(passo)
        return plano

    def planejar_remover_pastas(self, pastas: Iterable[str | Path], descricao: str = "remover pastas vazias") -> Plano:
        """Prévia de remover pastas VAZIAS (só remove se continuar vazia na hora; o desfazer recria)."""
        plano = Plano("remover_pasta", descricao)
        lista = [Path(p).resolve() for p in pastas]
        no_plano = set(lista)

        def vazia(pasta: Path) -> bool:
            """Vazia, ou só com subpastas que também estão no plano (e serão removidas antes)."""
            return all(disco.eh_pasta(pasta / n) and (pasta / n) in no_plano and vazia(pasta / n)
                       for n in disco.listar(pasta))

        for pasta in sorted(lista, key=lambda p: (-len(p.parts), str(p).casefold())):  # mais funda primeiro
            passo = Passo(origem=pasta, destino=None, tamanho=0)
            if not disco.eh_pasta(pasta):
                passo.problema = "pasta não existe"
            elif self._area(pasta) is None:
                passo.problema = self._fora_da_area(pasta)
            elif pasta in self.areas:
                passo.problema = "é a própria área: não removo"
            elif self._em_pasta_bloqueada(pasta / "x"):
                passo.problema = "dentro de pasta bloqueada (regra 3): não mexo"
            elif not vazia(pasta):
                passo.problema = "não está vazia"
            plano.passos.append(passo)
        return plano

    def planejar_esvaziar(self) -> Plano:
        """Lista o que seria APAGADO DE VEZ: só itens do histórico que ainda estão na quarentena.
        Quarentena de uma unidade fora das áreas (modo PC real desligado) fica de fora."""
        plano = Plano("esvaziar", "esvaziar a quarentena (apaga de vez)")
        for op in self.indice.itens_na_quarentena():
            caminho = Path(op["destino"])
            passo = Passo(origem=caminho, destino=None, tamanho=op["tamanho"] or 0,
                          hash_esperado=op["hash_completo"], ref_operacao=op["id"])
            if not disco.eh_arquivo(caminho):
                passo.problema = "não está mais na quarentena"
            elif self._area(caminho) is None:
                passo.problema = self._fora_da_area(caminho)
            plano.passos.append(passo)
        return plano

    # --- executar --------------------------------------------------------------

    def executar(
        self,
        plano: Plano,
        *,
        lote_id: int | None = None,
        parar: Callable[[], bool] = lambda: False,
        ao_progredir: Callable[[int, int], None] | None = None,
    ) -> Resultado:
        """Executa o plano. `lote_id` junta este plano a um lote já existente (ex.: remover as
        pastas que o organizar esvaziou entra no MESMO lote, e um único desfazer volta tudo).

        `parar()` é consultado entre um arquivo e outro (nunca no meio de um rename; numa cópia
        longa do "mover de unidade", também entre um bloco e outro — e aí a cópia é desfeita);
        `ao_progredir(feitos, total)` alimenta a barra de progresso da interface."""
        resultado = Resultado()
        if not plano.validos:
            return resultado
        resultado.lote_id = lote_id or self.indice.criar_lote(plano.tipo, plano.descricao, _agora())
        self.indice.confirmar()
        if plano.tipo == "mover_unidade":
            from .transferir import executar_passo  # import aqui: transferir usa esta classe

            def acao(passo, lote, _):
                if passo.remover_pasta:
                    self._remover_pasta(passo, lote, _)
                else:
                    executar_passo(self, passo, lote, parar)
        else:
            acao = {"quarentena": self._mover, "restaurar": self._restaurar, "esvaziar": self._apagar,
                    "organizar": self._organizar, "remover_pasta": self._remover_pasta}[plano.tipo]
        hashes_mantidos: dict[Path, str] = {}
        raizes: set[Path] = set()  # quarentenas tocadas: no fim, tiram-se as pastas que ficaram vazias
        validos = plano.validos
        for i, passo in enumerate(validos):
            if parar():
                resultado.cancelado = True
                break
            try:
                acao(passo, resultado.lote_id, hashes_mantidos)
                resultado.feitos.append(passo)
            except Cancelado:
                resultado.cancelado = True
                break
            except (OSError, OperacaoRecusada) as erro:
                resultado.falhas.append((passo, mensagem_de_erro(erro)))
            finally:
                raizes |= {r for c in (passo.origem, passo.destino) if c and (r := self._raiz_da_quarentena(c))}
                if plano.tipo == "mover_unidade" and not passo.remover_pasta:
                    raizes.add(self.local(passo.origem))  # se voltou atrás, sobram pastas vazias lá
            if ao_progredir:
                ao_progredir(i + 1, len(validos))
        if plano.tipo == "restaurar":
            # Uma pasta criada pelo organizar (ex.: "Textos") só fica vazia depois que TODOS os
            # arquivos do lote voltam; por isso a limpeza final vai da pasta mais funda para a mais rasa.
            criadas: list[str] = []
            for passo in resultado.feitos:
                original = self.indice.operacao(passo.ref_operacao) if passo.ref_operacao else None
                if original is not None and original["tipo"] in ("organizar", "mover_unidade"):
                    criadas += json.loads(original["pastas_criadas"] or "[]")
            self._remover_pastas_criadas(json.dumps(criadas))
        self._remover_pastas_vazias(raizes)
        self.indice.confirmar()
        return resultado

    def _no_disco(self, op_id: int, acao: Callable[[], None]) -> None:
        """Executa a mudança no disco; se o Windows recusar (em uso, sem permissão...),
        marca a operação como "falhou" na hora — o disco não mudou."""
        try:
            acao()
        except OSError as erro:
            self.indice.concluir_operacao(op_id, "falhou", _agora(), mensagem_de_erro(erro))
            self.indice.confirmar()
            raise

    def _mover(self, passo: Passo, lote_id: int, hashes_mantidos: dict[Path, str],
               ref_operacao: int | None = None) -> None:
        origem = passo.origem
        destino = self._destino_na_quarentena(origem, lote_id)
        self._conferir_limite(origem, destino)
        if not self._mesma_unidade(origem, destino):
            raise OperacaoRecusada("a quarentena fica em outra unidade (não copio arquivos)")

        hash_atual = self.hasher.completo(origem)
        if passo.hash_esperado and hash_atual != passo.hash_esperado:
            raise OperacaoRecusada("o arquivo mudou desde a prévia; rode escanear e tente de novo")
        if passo.manter is not None:
            # Nunca manda a última cópia: a que fica tem que existir e ser igual.
            if passo.manter not in hashes_mantidos:
                if not disco.eh_arquivo(passo.manter):
                    raise OperacaoRecusada(f"a cópia que ficaria sumiu: {passo.manter}")
                hashes_mantidos[passo.manter] = self.hasher.completo(passo.manter)
            if hashes_mantidos[passo.manter] != hash_atual:
                raise OperacaoRecusada(f"a cópia que ficaria não é mais igual: {passo.manter}")
        if disco.existe(destino):
            raise OperacaoRecusada(f"já existe algo no destino: {destino}")

        disco.criar_pastas(destino.parent)
        passo.destino = destino
        op_id = self.indice.registrar_operacao(
            lote_id=lote_id, tipo="quarentena", origem=str(origem), destino=str(destino),
            pasta_raiz=passo.pasta_raiz, tamanho=passo.tamanho, hash_completo=hash_atual,
            ref_operacao=ref_operacao, agora=_agora(),
        )
        self.gancho(ANTES_DE_MEXER, passo)
        self._no_disco(op_id, lambda: disco.renomear(origem, destino))  # mesma unidade: instantâneo, não copia
        self.gancho(DEPOIS_DE_MEXER, passo)
        self._concluir_quarentena(op_id, origem, _agora())
        self.indice.confirmar()

    def _concluir_quarentena(self, op_id: int, origem: Path, agora: str) -> None:
        self.indice.concluir_operacao(op_id, "feita", agora, situacao="na_quarentena")
        self.indice.remover_arquivo(str(origem))
        op = self.indice.operacao(op_id)
        ref = self.indice.operacao(op["ref_operacao"]) if op["ref_operacao"] else None
        if ref is not None and ref["tipo"] == "mover_unidade":
            # Desfazer "mover para outra unidade": a cópia foi para a quarentena → a mudança foi desfeita.
            self.indice.mudar_situacao(ref["id"], "desfeito")

    def _restaurar(self, passo: Passo, lote_id: int, hashes: dict[Path, str]) -> None:
        if passo.recriar_pasta:
            self._recriar_pasta(passo, lote_id)
            return
        if passo.quarentenar_copia:
            self._mover(passo, lote_id, hashes, ref_operacao=passo.ref_operacao)
            return
        origem, destino = passo.origem, passo.destino
        assert destino is not None
        self._conferir_limite(origem, destino)
        if passo.hash_esperado and self.hasher.completo(origem) != passo.hash_esperado:
            raise OperacaoRecusada("o arquivo na quarentena não bate com o hash do histórico; não mexi")
        if disco.existe(destino):
            raise OperacaoRecusada(f"já existe um arquivo em {destino}; não sobrescrevo")

        disco.criar_pastas(destino.parent)
        op_id = self.indice.registrar_operacao(
            lote_id=lote_id, tipo="restaurar", origem=str(origem), destino=str(destino),
            pasta_raiz=passo.pasta_raiz, tamanho=passo.tamanho, hash_completo=passo.hash_esperado,
            ref_operacao=passo.ref_operacao, agora=_agora(),
        )
        self.gancho(ANTES_DE_MEXER, passo)
        self._no_disco(op_id, lambda: disco.renomear(origem, destino))
        self.gancho(DEPOIS_DE_MEXER, passo)
        self._concluir_restaurar(self.indice.operacao(op_id), destino, _agora())
        self.indice.confirmar()

    def _concluir_restaurar(self, op, destino: Path, agora: str) -> None:
        erro = None
        if op["hash_completo"] and self.hasher.completo(destino) != op["hash_completo"]:
            erro = "voltou com hash diferente do original"
        self.indice.concluir_operacao(op["id"], "feita", agora, erro)
        self.indice.mudar_situacao(op["ref_operacao"], "restaurado")
        original = self.indice.operacao(op["ref_operacao"])
        if original is not None and original["tipo"] == "organizar":
            # Desfazer um organizar: o arquivo continua no índice, só volta o caminho
            # (mantém descrição e hashes) e somem as pastas que o organizar criou, se vazias.
            self.indice.mudar_caminho(op["origem"], str(destino))
            self._remover_pastas_criadas(original["pastas_criadas"])
        else:
            pasta_raiz = op["pasta_raiz"] or str(destino.parent)
            indexar_arquivo(destino, self.indice, pasta_raiz)
        if erro:
            raise OperacaoRecusada(erro)

    def _remover_pasta(self, passo: Passo, lote_id: int, _: dict[Path, str]) -> None:
        pasta = passo.origem
        self._conferir_limite(pasta)
        if disco.listar(pasta):
            raise OperacaoRecusada("a pasta não está mais vazia; não removi")
        op_id = self.indice.registrar_operacao(
            lote_id=lote_id, tipo="remover_pasta", origem=str(pasta), destino="", pasta_raiz=None,
            tamanho=0, hash_completo=None, ref_operacao=None, agora=_agora(),
        )
        self.gancho(ANTES_DE_MEXER, passo)
        self._no_disco(op_id, lambda: disco.remover_pasta_vazia(pasta))
        self.gancho(DEPOIS_DE_MEXER, passo)
        self.indice.concluir_operacao(op_id, "feita", _agora(), situacao="removida")
        self.indice.confirmar()

    def _recriar_pasta(self, passo: Passo, lote_id: int) -> None:
        pasta = passo.destino
        self._conferir_limite(pasta)
        op_id = self.indice.registrar_operacao(
            lote_id=lote_id, tipo="recriar_pasta", origem="", destino=str(pasta), pasta_raiz=None,
            tamanho=0, hash_completo=None, ref_operacao=passo.ref_operacao, agora=_agora(),
        )
        self._no_disco(op_id, lambda: disco.criar_pastas(pasta))
        self.indice.concluir_operacao(op_id, "feita", _agora())
        self.indice.mudar_situacao(passo.ref_operacao, "restaurado")
        self.indice.confirmar()

    def _organizar(self, passo: Passo, lote_id: int, _: dict[Path, str]) -> None:
        origem, destino = passo.origem, passo.destino
        assert destino is not None
        self._conferir_limite(origem, destino)
        if not self._mesma_unidade(origem, destino):
            raise OperacaoRecusada("destino em outra unidade (não copio arquivos)")
        hash_atual = self.hasher.completo(origem)
        if passo.hash_esperado and hash_atual != passo.hash_esperado:
            raise OperacaoRecusada("o arquivo mudou desde a prévia; rode escanear e tente de novo")
        if disco.existe(destino):
            raise OperacaoRecusada(f"já existe um arquivo em {destino}; não sobrescrevo")

        criadas = self.pastas_que_faltam(destino.parent)
        disco.criar_pastas(destino.parent)
        op_id = self.indice.registrar_operacao(
            lote_id=lote_id, tipo="organizar", origem=str(origem), destino=str(destino),
            pasta_raiz=passo.pasta_raiz, tamanho=passo.tamanho, hash_completo=hash_atual,
            ref_operacao=None, agora=_agora(), pastas_criadas=json.dumps(criadas),
        )
        self.gancho(ANTES_DE_MEXER, passo)
        self._no_disco(op_id, lambda: disco.renomear(origem, destino))
        self.gancho(DEPOIS_DE_MEXER, passo)
        self._concluir_organizar(op_id, origem, destino, passo.pasta_raiz, _agora())
        self.indice.confirmar()

    def pastas_que_faltam(self, pasta: Path) -> list[str]:
        """As pastas (dentro das áreas) que ainda não existem até `pasta`, da mais rasa à mais funda."""
        return [str(p) for p in reversed((pasta, *pasta.parents))
                if self._area(p) is not None and not disco.existe(p)]

    def _concluir_organizar(self, op_id: int, origem: Path, destino: Path, pasta_raiz: str | None,
                            agora: str) -> None:
        self.indice.concluir_operacao(op_id, "feita", agora, situacao="organizado")
        self.indice.mudar_caminho(str(origem), str(destino), pasta_raiz)

    def _remover_pastas_criadas(self, pastas_json: str | None) -> None:
        """Remove (se ficaram vazias) só as pastas que o próprio app criou (organizar, mover de unidade)."""
        for pasta in sorted(set(json.loads(pastas_json or "[]")), key=len, reverse=True):
            try:
                disco.remover_pasta_vazia(pasta)
            except OSError:
                pass

    def _apagar(self, passo: Passo, lote_id: int, _: dict[Path, str]) -> None:
        caminho = passo.origem
        self._conferir_limite(caminho)
        if passo.hash_esperado and self.hasher.completo(caminho) != passo.hash_esperado:
            raise OperacaoRecusada("o arquivo na quarentena não bate com o histórico; não apaguei")
        op_id = self.indice.registrar_operacao(
            lote_id=lote_id, tipo="esvaziar", origem=str(caminho), destino="",
            pasta_raiz=None, tamanho=passo.tamanho, hash_completo=passo.hash_esperado,
            ref_operacao=passo.ref_operacao, agora=_agora(),
        )
        self.gancho(ANTES_DE_MEXER, passo)
        # única remoção definitiva (exceção do Esvaziar, regra 1)
        self._no_disco(op_id, lambda: os.remove(disco.no_disco(caminho)))
        self.gancho(DEPOIS_DE_MEXER, passo)
        self._concluir_esvaziar(op_id, passo.ref_operacao, _agora())
        self.indice.confirmar()

    def _concluir_esvaziar(self, op_id: int, ref_operacao: int | None, agora: str) -> None:
        self.indice.concluir_operacao(op_id, "feita", agora)
        if ref_operacao is not None:
            self.indice.mudar_situacao(ref_operacao, "esvaziado")
            item = self.indice.operacao(ref_operacao)
            mudanca = self.indice.operacao(item["ref_operacao"]) if item and item["ref_operacao"] else None
            if mudanca is not None and mudanca["tipo"] == "mover_unidade" and mudanca["situacao"] == "movido":
                # O original de um "mover para outra unidade" foi apagado: a cópia é a única agora.
                self.indice.mudar_situacao(mudanca["id"], "definitivo")

    @staticmethod
    def _raiz_da_quarentena(caminho: Path) -> Path | None:
        for pasta in Path(caminho).parents:
            if pasta.name.casefold() == NOME_QUARENTENA.casefold():
                return pasta
        return None

    def _remover_pastas_vazias(self, raizes: set[Path] | None = None) -> None:
        """Depois de mover/esvaziar/desfazer, remove só as pastas que ficaram vazias DENTRO das
        quarentenas usadas (a própria `_quarentena` fica)."""
        for raiz in raizes if raizes is not None else {self.local(self.limite)}:
            if not disco.eh_pasta(raiz):
                continue
            for pasta, _, _ in disco.percorrer(raiz, de_baixo_para_cima=True):
                if Path(pasta) != raiz and not disco.listar(pasta):
                    disco.remover_pasta_vazia(pasta)
