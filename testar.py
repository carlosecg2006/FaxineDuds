"""Roda a suíte inteira em DOIS processos: os testes comuns e os de interface (test_gui*.py).

Por quê: na suíte num processo só, o Qt às vezes aborta o Python ("Fatal Python error:
Aborted") no primeiro teste com QThread depois dos testes comuns — cerca de 1 rodada em 10,
nunca com os testes de interface sozinhos. Causa provável: o Qt (PySide6 + Python 3.14)
destruindo uma QThread/objeto Qt num momento ruim do coletor de lixo, num processo que já tem
muito estado dos outros testes. Separar os processos elimina isso (ver CLAUDE.md).

Uso:  .venv\\Scripts\\python testar.py  [argumentos extras do pytest]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
PARTES = (
    ("testes comuns", ["tests", "--ignore-glob=tests/test_gui*.py"]),
    ("testes de interface", ["tests/test_gui.py", "tests/test_gui_7b.py"]),
)


def main(extras: list[str]) -> int:
    codigos = []
    for nome, alvos in PARTES:
        print(f"== {nome}", flush=True)
        r = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *alvos, *extras], cwd=RAIZ)
        codigos.append(r.returncode)
        print(f"== {nome}: {'OK' if r.returncode == 0 else f'FALHOU (código {r.returncode})'}", flush=True)
    return 0 if all(c == 0 for c in codigos) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
