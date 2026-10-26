"""Gera capturas de cada tela da interface (sem abrir janela) em docs/capturas/.

Usa o índice real da pasta_teste. Não move nada: só analisa, sugere (sem IA) e mostra.
Uso: python ferramentas/capturas_gui.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")  # o modo offscreen não acha as fontes sozinho
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from PySide6.QtWidgets import QApplication  # noqa: E402

from faxineiro.gui.app import Janela, aplicar_tema, criar_ambiente  # noqa: E402

DESTINO = RAIZ / "docs" / "capturas"


def esperar(app: QApplication, janela: Janela) -> None:
    while janela.amb.gerente.ocupado:
        app.processEvents()
        time.sleep(0.05)
    for _ in range(10):
        app.processEvents()


def main() -> int:
    app = QApplication(sys.argv)
    aplicar_tema(app, escuro=False)
    janela = Janela(criar_ambiente())
    janela.resize(1180, 760)
    janela.show()
    DESTINO.mkdir(parents=True, exist_ok=True)

    def capturar(nome: str) -> None:
        esperar(app, janela)
        janela.grab().save(str(DESTINO / f"{nome}.png"))
        print("capturada:", nome)

    janela.lateral.setCurrentRow(0)
    capturar("1_inicio")

    janela.lateral.setCurrentRow(1)
    exp = janela.telas[1]
    raiz = exp.arvore.topLevelItem(0)
    for i in range(raiz.childCount()):
        if raiz.child(i).text(0) == "Amostras_IA":
            exp.arvore.setCurrentItem(raiz.child(i))
    exp.tabela.selectRow(2)
    capturar("2_explorador")

    janela.lateral.setCurrentRow(2)
    janela.telas[2].modo_teste.setChecked(True)
    janela.telas[2].analisar()
    capturar("3_faxina")

    janela.lateral.setCurrentRow(3)
    org = janela.telas[3]
    org.usar_ia.setChecked(False)  # captura rápida, sem chamar a IA
    org.sugerir()
    capturar("4_organizar")

    janela.lateral.setCurrentRow(4)
    capturar("5_quarentena")

    janela.lateral.setCurrentRow(5)
    janela.telas[5].verificar()
    capturar("6_ia")

    aplicar_tema(app, escuro=True)
    janela.lateral.setCurrentRow(0)
    capturar("7_inicio_escuro")
    janela.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
