"""Gera dist\\Faxineiro\\Faxineiro.exe com o PyInstaller (Fase 7B).

Modo pasta (--onedir), e não arquivo único: o arquivo único se descompacta numa pasta
temporária toda vez que abre (mais lento e mais RAM — o PC tem 4 GB). O ffmpeg NÃO vai
dentro: o app continua usando D:\\FaxineDuds\\externos\\ffmpeg.

Uso:  .venv\\Scripts\\python ferramentas\\gerar_exe.py
Depois: powershell -ExecutionPolicy Bypass -File ferramentas\\criar_atalho.ps1
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

ARGS = [
    "--noconfirm",
    "--windowed",  # sem janela preta de console
    "--onedir",
    "--name", "Faxineiro",
    "--distpath", str(RAIZ / "dist"),
    "--workpath", str(RAIZ / "build"),
    "--specpath", str(RAIZ / "build"),
    "--paths", str(RAIZ),
    "--collect-data", "puremagic",  # a tabela de "números mágicos" (tipo real do arquivo)
    # Só QtCore/QtGui/QtWidgets (PySide6-Essentials); o resto só aumentaria o .exe.
    "--exclude-module", "tkinter",
    "--exclude-module", "PySide6.QtNetwork",
    "--exclude-module", "PySide6.QtQml",
    "--exclude-module", "PySide6.QtQuick",
    "--exclude-module", "pytest",
    str(RAIZ / "ferramentas" / "entrada_exe.py"),
]


def main() -> int:
    r = subprocess.run([sys.executable, "-m", "PyInstaller", *ARGS], cwd=RAIZ)
    exe = RAIZ / "dist" / "Faxineiro" / "Faxineiro.exe"
    if r.returncode == 0 and exe.is_file():
        tamanho = sum(p.stat().st_size for p in exe.parent.rglob("*") if p.is_file())
        print(f"Pronto: {exe} ({tamanho / 1024 / 1024:.0f} MB na pasta dist\\Faxineiro)")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
