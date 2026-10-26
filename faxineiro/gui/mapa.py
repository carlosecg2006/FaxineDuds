"""Mapa de blocos (estilo WinDirStat): área = tamanho, cor = tipo que mais pesa na pasta."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from ..formato import formatar_bytes
from ..treemap import Retangulo, squarify

CORES = {
    "imagem": "#4e9af1", "video": "#e05d5d", "audio": "#b07ce8", "documento": "#4caf7a",
    "texto": "#8bc34a", "compactado": "#f0a742", "executavel": "#9e9e9e", "outro": "#78909c",
}


class MapaBlocos(QWidget):
    pastaClicada = Signal(str)  # nome da subpasta

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self._blocos: list[dict] = []
        self._retangulos: list[Retangulo] = []

    def definir_blocos(self, blocos: list[dict]) -> None:
        self._blocos = blocos
        self._calcular()
        self.update()

    def resizeEvent(self, evento) -> None:
        self._calcular()
        super().resizeEvent(evento)

    def _calcular(self) -> None:
        r = self.rect().adjusted(2, 2, -2, -2)
        self._retangulos = squarify([b["bytes"] for b in self._blocos], r.x(), r.y(), r.width(), r.height())

    def _bloco_em(self, x: float, y: float) -> dict | None:
        for ret in self._retangulos:
            if ret.x <= x < ret.x + ret.largura and ret.y <= y < ret.y + ret.altura:
                return self._blocos[ret.indice]
        return None

    def paintEvent(self, _evento) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        fundo = self.palette().window().color()
        p.fillRect(self.rect(), fundo)
        if not self._retangulos:
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Nada indexado ainda. Clique em Sincronizar.")
            return
        metricas = QFontMetrics(self.font())
        for ret in self._retangulos:
            bloco = self._blocos[ret.indice]
            caixa = QRectF(ret.x, ret.y, ret.largura, ret.altura).adjusted(1, 1, -1, -1)
            cor = QColor(CORES.get(bloco["categoria"], CORES["outro"]))
            p.fillRect(caixa, cor if bloco["pasta"] else cor.lighter(130))
            p.setPen(QPen(fundo, 2))
            p.drawRect(caixa)
            if caixa.width() > 60 and caixa.height() > 30:
                p.setPen(Qt.GlobalColor.white)
                texto = metricas.elidedText(bloco["nome"], Qt.TextElideMode.ElideRight, int(caixa.width()) - 8)
                p.drawText(caixa.adjusted(4, 4, -4, -4), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                           f"{texto}\n{formatar_bytes(bloco['bytes'])}")
        p.end()

    def mouseMoveEvent(self, evento) -> None:
        bloco = self._bloco_em(evento.position().x(), evento.position().y())
        if bloco:
            QToolTip.showText(evento.globalPosition().toPoint(),
                              f"{bloco['nome']}\n{formatar_bytes(bloco['bytes'])} em {bloco['quantidade']} arquivo(s)\n"
                              f"mais pesado: {bloco['categoria']}" + ("\n(clique para entrar)" if bloco["pasta"] else ""),
                              self)

    def mousePressEvent(self, evento) -> None:
        bloco = self._bloco_em(evento.position().x(), evento.position().y())
        if bloco and bloco["pasta"]:
            self.pastaClicada.emit(bloco["nome"])
