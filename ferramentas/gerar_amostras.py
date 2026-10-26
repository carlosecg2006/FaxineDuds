"""Cria arquivos sintéticos em pasta_teste para testar o Faxineiro à mão.

Só cria arquivos que ainda não existem: nunca sobrescreve nem apaga nada.
Uso: python ferramentas/gerar_amostras.py
"""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from faxineiro.config import PASTA_TESTE  # noqa: E402
from tests.conftest import bytes_docx, bytes_jpeg, bytes_pdf, bytes_png, bytes_zip  # noqa: E402


def amostras() -> dict[str, bytes]:
    rnd = random.Random(42)
    arquivos: dict[str, bytes] = {}
    for i in range(1, 11):
        arquivos[f"Fotos/IMG_{i:04d}.png"] = bytes_png() + bytes([i])
    for i in range(1, 6):
        arquivos[f"Fotos/viagem/foto_{i}.jpg"] = bytes_jpeg() + bytes([i])
    arquivos["Fotos/IMG_0001 - Cópia.png"] = bytes_png() + bytes([1])  # duplicado exato
    for i in range(1, 6):
        arquivos[f"Documentos/boleto_{i}.pdf"] = bytes_pdf() + f"% {i}\n".encode()
    arquivos["Documentos/TCC_final.docx"] = bytes_docx()
    arquivos["Documentos/TCC_final_v2.docx"] = bytes_docx()  # duplicado exato
    arquivos["Documentos/anotacoes.txt"] = "Aula de banco de dados: normalização\n".encode() * 20
    arquivos["Documentos/planilha.csv"] = b"nome;valor\narroz;10\nfeijao;8\n"
    arquivos["Downloads/instalador.zip"] = bytes_zip({"leiame.txt": b"instale"})
    arquivos["Downloads/foto_whatsapp.jpg"] = bytes_png()  # extensão errada (é PNG)
    arquivos["Downloads/arquivo_sem_extensao"] = bytes_pdf()  # PDF sem extensão
    arquivos["Downloads/video_grande.bin"] = bytes(rnd.getrandbits(8) for _ in range(2 * 1024 * 1024))
    arquivos["Downloads/vazio.txt"] = b""
    for i in range(1, 6):
        arquivos[f"Diversos/rascunho_{i}.md"] = f"# Rascunho {i}\nideias soltas\n".encode()
    arquivos["_quarentena/nao_deve_ser_indexado.txt"] = b"pasta bloqueada"
    # Fase 2 (Raio-X)
    filme = bytes(rnd.getrandbits(8) for _ in range(3 * 1024 * 1024))
    arquivos["Videos/filme_ferias.mp4.bin"] = filme
    arquivos["Downloads/filme_ferias (1).mp4.bin"] = filme  # duplicado grande
    quase = bytes(rnd.getrandbits(8) for _ in range(1024 * 1024))
    arquivos["Videos/gravacao_parte1.bin"] = quase + b"A"  # mesmo tamanho e começo,
    arquivos["Videos/gravacao_parte2.bin"] = quase + b"B"  # mas NÃO são duplicados
    arquivos["Documentos/~$TCC_final.docx"] = b"rascunho temporario do word"
    arquivos["Downloads/programa.exe.crdownload"] = b"download pela metade" * 50
    arquivos["Downloads/cache.tmp"] = b"temporario" * 30
    arquivos["Fotos/Thumbs.db"] = b"miniaturas do windows" * 10
    return arquivos


PASTAS_VAZIAS = ["Projetos/antigo", "Projetos/vazio_com_sub/sub1/sub2", "Musicas"]


def main() -> int:
    criados = 0
    for relativo, dados in amostras().items():
        destino = PASTA_TESTE / relativo
        if destino.exists():
            continue
        destino.parent.mkdir(parents=True, exist_ok=True)
        with open(destino, "xb") as f:  # "x" falha se o arquivo já existir
            f.write(dados)
        criados += 1
    for relativa in PASTAS_VAZIAS:
        (PASTA_TESTE / relativa).mkdir(parents=True, exist_ok=True)
    total = sum(1 for _ in PASTA_TESTE.rglob("*") if _.is_file())
    print(f"Criados {criados} arquivos novos em {PASTA_TESTE} (total: {total}).")
    return 0


if __name__ == "__main__":
    os.chdir(RAIZ)
    sys.exit(main())
