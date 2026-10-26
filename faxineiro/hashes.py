"""Hash BLAKE3 em duas leituras: parcial (começo do arquivo) e completo."""

from __future__ import annotations

from pathlib import Path

from blake3 import blake3

TAMANHO_PARCIAL = 64 * 1024  # 64 KB
BLOCO = 1024 * 1024  # 1 MB por leitura


class Hasher:
    """Calcula os hashes e conta quanto leu (para progresso e para os testes)."""

    def __init__(self) -> None:
        self.parciais = 0
        self.completos = 0
        self.bytes_lidos = 0

    def parcial(self, caminho: str | Path) -> str:
        """Hash dos primeiros 64 KB. Para arquivos até 64 KB, é igual ao completo."""
        with open(caminho, "rb") as f:
            dados = f.read(TAMANHO_PARCIAL)
        self.parciais += 1
        self.bytes_lidos += len(dados)
        return blake3(dados).hexdigest()

    def completo(self, caminho: str | Path) -> str:
        """Hash do arquivo inteiro, lido em blocos (não carrega tudo na memória)."""
        h = blake3()
        with open(caminho, "rb") as f:
            while bloco := f.read(BLOCO):
                h.update(bloco)
                self.bytes_lidos += len(bloco)
        self.completos += 1
        return h.hexdigest()
