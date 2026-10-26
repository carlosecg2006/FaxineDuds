"""Miniaturas pequenas (96 px) com cache em disco e na memória.

`QImageReader.setScaledSize` decodifica a imagem já no tamanho pequeno: uma foto de 12 MP
não é carregada inteira na RAM. A miniatura fica em `dados/miniaturas/` (regra 4: só miniaturas
pequenas, nunca cópia do arquivo).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QImageReader, QPixmap, QPixmapCache

from ..config import RAIZ_PROJETO

TAMANHO = 96
PASTA_CACHE = RAIZ_PROJETO / "dados" / "miniaturas"
LIMITE_CACHE_MEMORIA_KB = 10 * 1024  # 10 MB de miniaturas na memória, no máximo


def chave(caminho: str | Path) -> str | None:
    """Muda se o arquivo mudar (data ou tamanho): a miniatura velha nunca é mostrada."""
    try:
        st = os.stat(caminho)
    except OSError:
        return None
    return hashlib.sha1(f"{Path(caminho).resolve()}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()


def gerar_miniatura(caminho: str | Path, pasta_cache: Path = PASTA_CACHE, tamanho: int = TAMANHO) -> Path | None:
    """Cria (ou reaproveita) a miniatura em disco. Roda bem fora da thread da janela (usa QImage)."""
    k = chave(caminho)
    if k is None:
        return None
    destino = pasta_cache / f"{k}.jpg"
    if destino.exists():
        return destino
    leitor = QImageReader(str(caminho))
    leitor.setAutoTransform(True)  # respeita a rotação da foto (EXIF)
    original = leitor.size()
    if not original.isValid():
        return None
    leitor.setScaledSize(original.scaled(QSize(tamanho, tamanho), Qt.AspectRatioMode.KeepAspectRatio))
    imagem: QImage = leitor.read()
    if imagem.isNull():
        return None
    pasta_cache.mkdir(parents=True, exist_ok=True)
    imagem.save(str(destino), "JPG", 80)
    return destino


class _Sinais(QObject):
    pronta = Signal(str, str)  # caminho do arquivo, caminho da miniatura ("" = não deu)


class _Trabalho(QRunnable):
    def __init__(self, caminho: str, pasta_cache: Path, sinais: _Sinais) -> None:
        super().__init__()
        self.caminho, self.pasta_cache, self.sinais = caminho, pasta_cache, sinais

    def run(self) -> None:
        mini = gerar_miniatura(self.caminho, self.pasta_cache)
        self.sinais.pronta.emit(self.caminho, str(mini) if mini else "")


class CarregadorMiniaturas(QObject):
    """Pede miniaturas sem travar a janela; responde pelo sinal `pronta(caminho, QPixmap)`."""

    pronta = Signal(str, QPixmap)

    def __init__(self, pasta_cache: Path = PASTA_CACHE, parent: QObject | None = None) -> None:
        super().__init__(parent)
        QPixmapCache.setCacheLimit(LIMITE_CACHE_MEMORIA_KB)
        self.pasta_cache = pasta_cache
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)  # uma por vez: pouca RAM
        self._sinais = _Sinais()
        self._sinais.pronta.connect(self._chegou)

    def pedir(self, caminho: str) -> None:
        k = chave(caminho)
        if k is None:
            return
        pix = QPixmap()
        if QPixmapCache.find(k, pix):
            self.pronta.emit(caminho, pix)
            return
        self.pool.start(_Trabalho(caminho, self.pasta_cache, self._sinais))

    def _chegou(self, caminho: str, mini: str) -> None:
        if not mini:
            return
        pix = QPixmap(mini)
        k = chave(caminho)
        if k:
            QPixmapCache.insert(k, pix)
        self.pronta.emit(caminho, pix)
