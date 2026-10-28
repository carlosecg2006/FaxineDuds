"""Ponto de entrada do Faxineiro.exe (PyInstaller): abre a janela.

O .exe usa os mesmos dados do modo desenvolvimento (D:\\FaxineDuds\\dados, pasta_teste e o
ffmpeg em externos\\) — ver config._raiz_do_projeto.

Sem console (--windowed), o sys.stderr do PyInstaller é None: qualquer erro sumiria. Por isso
os erros (e um retrato de onde o programa está, se travar) vão para dados\\faxineiro_exe.log.
"""

import faulthandler
import sys

from faxineiro.config import RAIZ_PROJETO

if __name__ == "__main__":
    log = None
    if sys.stderr is None:
        (RAIZ_PROJETO / "dados").mkdir(exist_ok=True)
        log = open(RAIZ_PROJETO / "dados" / "faxineiro_exe.log", "w", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
        faulthandler.enable(log)  # se o Qt derrubar o processo, fica o rastro aqui
    try:
        from faxineiro.gui.app import principal

        codigo = principal()
    except BaseException:
        import traceback

        traceback.print_exc()
        raise
    sys.exit(codigo)
