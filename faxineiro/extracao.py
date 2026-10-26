"""Lê só o COMEÇO do texto de um arquivo, já cortado (lição do Local File Organizer #30)."""

from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path

LIMITE_CARACTERES = 1500
_LER_BYTES = 16 * 1024  # para texto puro, não precisa ler mais que isso

_TAGS = re.compile(rb"<[^>]+>")
_ESPACOS = re.compile(r"\s+")


def _limpar(texto: str, limite: int) -> str | None:
    texto = _ESPACOS.sub(" ", texto).strip()
    return texto[:limite] or None


def _texto_puro(caminho: Path, limite: int) -> str | None:
    with open(caminho, "rb") as f:
        dados = f.read(_LER_BYTES)
    if dados.startswith((b"\xff\xfe", b"\xfe\xff")):
        return _limpar(dados.decode("utf-16", errors="replace"), limite)
    try:
        texto = dados.decode("utf-8-sig")
    except UnicodeDecodeError as erro:
        if erro.start >= len(dados) - 3:  # cortou no meio de um caractere, no fim do pedaço lido
            texto = dados[: erro.start].decode("utf-8-sig")
        else:  # arquivos antigos do Windows (ANSI)
            texto = dados.decode("cp1252", errors="replace")
    return _limpar(texto, limite)


def _xml_do_zip(caminho: Path, partes: list[str], limite: int) -> str | None:
    """docx/xlsx/pptx são zips com XML dentro: tira as tags e fica com o texto."""
    pedacos: list[str] = []
    total = 0
    with zipfile.ZipFile(caminho) as z:
        nomes = set(z.namelist())
        for parte in partes:
            alvos = sorted(n for n in nomes if re.fullmatch(parte, n))
            for nome in alvos:
                with z.open(nome) as f:
                    bruto = f.read(256 * 1024)  # nunca lê o XML inteiro de um arquivo gigante
                texto = html.unescape(_TAGS.sub(b" ", bruto).decode("utf-8", errors="replace"))
                pedacos.append(texto)
                total += len(texto)
                if total > limite * 2:
                    return _limpar(" ".join(pedacos), limite)
    return _limpar(" ".join(pedacos), limite)


def _pdf(caminho: Path, limite: int) -> str | None:
    from pypdf import PdfReader

    leitor = PdfReader(str(caminho))
    if not leitor.pages:
        return None
    return _limpar(leitor.pages[0].extract_text() or "", limite)


def comeco_do_texto(caminho: str | Path, tipo_real: str, limite: int = LIMITE_CARACTERES) -> str | None:
    """Devolve até `limite` caracteres do começo do texto, ou None se não houver texto legível.

    Nunca levanta erro por arquivo corrompido: devolve None (o arquivo será descrito por regras).
    """
    caminho = Path(caminho)
    try:
        if tipo_real == "texto":
            return _texto_puro(caminho, limite)
        if tipo_real == "docx":
            return _xml_do_zip(caminho, [r"word/document\.xml"], limite)
        if tipo_real == "pptx":
            return _xml_do_zip(caminho, [r"ppt/slides/slide\d+\.xml"], limite)
        if tipo_real == "xlsx":
            return _xml_do_zip(caminho, [r"xl/sharedStrings\.xml", r"xl/worksheets/sheet\d+\.xml"], limite)
        if tipo_real == "pdf":
            return _pdf(caminho, limite)
    except Exception:  # arquivo corrompido/protegido: vira descrição por regras, sem travar
        return None
    return None
