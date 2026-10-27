"""Fase 7B — cria as pastas de teste para "mover para outra unidade" com arquivos de verdade:

    C:\\Users\\<usuário>\\FaxineiroTeste   e   D:\\FaxineiroTeste

Só CRIA arquivos (conteúdo aleatório, com cabeçalho real) e recusa rodar se a pasta já existir.
Nunca apaga nada. Uso: .venv\\Scripts\\python ferramentas\\gerar_teste_unidades.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from faxineiro.config import PASTA_DO_USUARIO  # noqa: E402

PASTAS = (PASTA_DO_USUARIO / "FaxineiroTeste", Path(r"D:\FaxineiroTeste"))
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt "
MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"


def gerar(base: Path, semente: int) -> list[Path]:
    r = random.Random(semente)
    arquivos = {
        "Samples Teste/Kicks/kick 01.wav": WAV + r.randbytes(40_000),
        "Samples Teste/Kicks/kick 02.wav": WAV + r.randbytes(52_000),
        "Samples Teste/Loops/loop 120bpm.wav": WAV + r.randbytes(300_000),
        "Samples Teste/leia-me.txt": "Pasta de teste do Faxineiro (Fase 7B).\n".encode("utf-8"),
        "video de teste.mp4": MP4 + r.randbytes(3 * 1024 * 1024),  # 3 MB: mais de um bloco de 1 MB
        "anotacao solta.txt": f"Arquivo de teste criado em {base}.\n".encode("utf-8"),
    }
    criados = []
    for rel, dados in arquivos.items():
        caminho = base / rel
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with open(caminho, "xb") as f:  # "x": nunca sobrescreve
            f.write(dados)
        criados.append(caminho)
    (base / "Samples Teste" / "Pasta vazia").mkdir()
    return criados


def main() -> int:
    for pasta in PASTAS:
        if pasta.exists():
            print(f"Já existe {pasta}: não mexo (rode só uma vez).")
            return 1
    for semente, pasta in enumerate(PASTAS, 1):
        criados = gerar(pasta, semente)
        print(f"{pasta}: {len(criados)} arquivos, {sum(c.stat().st_size for c in criados):,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
