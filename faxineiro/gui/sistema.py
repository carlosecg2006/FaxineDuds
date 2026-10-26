"""Conversa com o Windows: abrir no programa padrão e mostrar o arquivo na pasta. Só abre, nunca altera."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def abrir_arquivo(caminho: str | Path) -> bool:
    """Abre no programa padrão do Windows (o mesmo do clique duplo no Explorador)."""
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(caminho))))


def mostrar_na_pasta(caminho: str | Path) -> None:
    """Abre o Explorador do Windows na pasta, com o arquivo já selecionado."""
    caminho = Path(caminho)
    if sys.platform == "win32":
        subprocess.Popen(["explorer", f"/select,{caminho}"])
    else:  # pragma: no cover
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(caminho.parent)))
