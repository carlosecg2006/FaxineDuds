"""Botão "Mover para outra unidade…" (Explorador e aba Pesados): destino, prévia e execução."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from ..config import PASTA_DO_USUARIO
from ..formato import formatar_bytes
from ..transferir import planejar_mover_unidade
from .dialogos import confirmar_previa


def destino_sugerido(origem: Path) -> Path:
    """Começa a escolha pela OUTRA unidade: do C: sugere o D:\\, do D: sugere a pasta do usuário."""
    if Path(origem).drive.upper() == PASTA_DO_USUARIO.drive.upper():
        return Path("D:\\")
    return PASTA_DO_USUARIO


def mover_para_outra_unidade(
    amb,
    parent: QWidget,
    caminhos: list[str | Path],
    *,
    escolher_destino: Callable[[Path], str | None] | None = None,
    confirmar: Callable | None = None,
    ao_terminar: Callable | None = None,
) -> bool:
    """Escolhe a pasta de destino, mostra a prévia (espaço, quarentena, aviso dos programas) e
    move em segundo plano, com progresso por bytes e Cancelar."""
    if not caminhos:
        amb.mensagem("Escolha pelo menos um arquivo ou pasta.")
        return False
    inicio = destino_sugerido(Path(caminhos[0]))
    escolher_destino = escolher_destino or (lambda comeco: QFileDialog.getExistingDirectory(
        parent, "Mover para qual pasta (em OUTRA unidade)?", str(comeco)))
    destino = escolher_destino(inicio)
    if not destino:
        return False
    plano = planejar_mover_unidade(amb.quarentena(amb.leitura), caminhos, destino)
    confirmar = confirmar or confirmar_previa
    if not confirmar(plano, amb.pasta, "mover para outra unidade", parent):
        return False
    total = plano.total_bytes

    def trabalho(ctx):
        feitos = [0]  # bytes dos arquivos já terminados

        def progredir(f, t):
            feitos[0] = sum(p.tamanho for p in plano.validos[:f])

        with amb.abrir_indice() as indice:
            q = amb.quarentena(indice)
            q.ao_copiar = lambda n: ctx.avisar(
                (feitos[0] + n) // 1024, max(total // 1024, 1),
                f"Copiando e conferindo: {formatar_bytes(feitos[0] + n)} de {formatar_bytes(total)}")
            return q.executar(plano, parar=ctx.parar, ao_progredir=progredir)

    def pronto(r) -> None:
        movidos = [p for p in r.feitos if not p.remover_pasta]
        unidades = sorted({p.origem.drive.upper() for p in movidos})
        texto = f"{len(movidos)} arquivo(s) movido(s) com hash conferido (lote {r.lote_id})."
        if unidades:
            texto += f" O espaço do {', '.join(unidades)} só é liberado ao esvaziar a quarentena."
        if r.cancelado:
            texto += " Cancelado: o arquivo que estava no meio voltou para o lugar."
        amb.mensagem(texto)
        if r.falhas:
            QMessageBox.warning(parent, "Mover para outra unidade",
                                "\n".join(f"{p.origem.name}: {m}" for p, m in r.falhas[:20]))
        if ao_terminar:
            ao_terminar(r)

    return amb.rodar("Movendo para outra unidade", trabalho, pronto)
