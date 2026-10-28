"""Operações longas em segundo plano, sem congelar a janela.

Uma Tarefa roda uma função comum numa QThread. A função recebe um `Contexto` com:
- `ctx.parar()`  → True quando o usuário clicou em Cancelar (passado como `parar=` às funções);
- `ctx.avisar(feitos, total, texto)` → atualiza a barra de progresso.

Regra importante: cada tarefa abre a PRÓPRIA conexão com o índice (SQLite não se compartilha entre threads).
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal


class Contexto:
    def __init__(self, emitir: Callable[[int, int, str], None]) -> None:
        self._emitir = emitir
        self.cancelado = False

    def parar(self) -> bool:
        return self.cancelado

    def avisar(self, feitos: int = 0, total: int = 0, texto: str = "") -> None:
        self._emitir(int(feitos), int(total), texto)


class Tarefa(QThread):
    progresso = Signal(int, int, str)  # feitos, total (0 = não sabe), texto

    def __init__(self, titulo: str, funcao: Callable[[Contexto], Any], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.titulo = titulo
        self.funcao = funcao
        self.ctx = Contexto(self.progresso.emit)
        self.resultado: Any = None
        self.erro: str | None = None

    def cancelar(self) -> None:
        self.ctx.cancelado = True

    def run(self) -> None:  # roda na thread de trabalho
        try:
            self.resultado = self.funcao(self.ctx)
        except Exception as erro:  # mostra o erro na janela em vez de derrubar o app
            self.erro = f"{erro}\n\n{traceback.format_exc(limit=3)}"


class GerenteTarefas(QObject):
    """Uma tarefa de cada vez (com 4 GB de RAM, duas operações pesadas juntas só atrapalham).

    O aviso de fim (`ao_terminar`) só é chamado DEPOIS que a thread acabou — assim dá para
    começar outra tarefa logo em seguida (ex.: mover e depois analisar de novo)."""

    comecou = Signal(str)
    progresso = Signal(int, int, str)
    acabou = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.atual: Tarefa | None = None

    @property
    def ocupado(self) -> bool:
        return self.atual is not None

    def iniciar(
        self,
        titulo: str,
        funcao: Callable[[Contexto], Any],
        ao_terminar: Callable[[Any], None] | None = None,
        ao_falhar: Callable[[str], None] | None = None,
    ) -> Tarefa | None:
        if self.ocupado:
            return None
        tarefa = Tarefa(titulo, funcao, self)
        tarefa.progresso.connect(self.progresso)
        # Enfileirada: o `finished` sai da thread de trabalho, mas o _fim tem que rodar na da janela.
        tarefa.finished.connect(lambda: self._fim(tarefa, ao_terminar, ao_falhar), Qt.ConnectionType.QueuedConnection)
        self.atual = tarefa
        self.comecou.emit(titulo)
        tarefa.start(QThread.Priority.LowPriority)  # prioridade baixa: o PC continua respondendo
        return tarefa

    def cancelar(self) -> None:
        if self.atual is not None:
            self.atual.cancelar()

    def esperar(self, ms: int = 30000) -> None:
        if self.atual is not None:
            self.atual.wait(ms)

    def _fim(self, tarefa: Tarefa, ao_terminar, ao_falhar) -> None:
        # O `finished` é emitido um instante ANTES de a thread acabar de verdade. Sem esperar,
        # destruir a tarefa (ou o gerente) nesse instante faz o Qt abortar o processo inteiro
        # ("QThread: Destroyed while thread is still running") — era o crash intermitente da suíte.
        tarefa.wait()
        self.atual = None
        self.acabou.emit()
        if tarefa.erro is not None:
            if ao_falhar:
                ao_falhar(tarefa.erro)
        elif ao_terminar:
            ao_terminar(tarefa.resultado)
        tarefa.deleteLater()
