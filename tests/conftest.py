"""Fixtures: criam arquivos falsos (mas com cabeçalho real) só em pastas temporárias."""

from __future__ import annotations

import io
import struct
import zipfile
import zlib
from pathlib import Path

import pytest

from faxineiro.indice import Indice


def bytes_png() -> bytes:
    def chunk(tipo: bytes, dados: bytes) -> bytes:
        return struct.pack(">I", len(dados)) + tipo + dados + struct.pack(">I", zlib.crc32(tipo + dados))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def bytes_jpeg() -> bytes:
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\x00" * 64 + b"\xff\xd9"


def bytes_pdf() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"


def bytes_zip(arquivos: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nome, dados in arquivos.items():
            z.writestr(nome, dados)
    return buf.getvalue()


def bytes_docx() -> bytes:
    content_types = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        b'<Override PartName="/word/document.xml" ContentType="application/'
        b'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        b"</Types>"
    )
    return bytes_zip({"[Content_Types].xml": content_types, "word/document.xml": b"<w:document/>"})


@pytest.fixture
def pasta(tmp_path: Path) -> Path:
    """Pasta temporária com alguns arquivos de tipos variados."""
    raiz = tmp_path / "amostra"
    (raiz / "fotos").mkdir(parents=True)
    (raiz / "docs").mkdir()
    (raiz / "fotos" / "praia.png").write_bytes(bytes_png())
    (raiz / "fotos" / "festa.jpg").write_bytes(bytes_jpeg())
    (raiz / "docs" / "contrato.pdf").write_bytes(bytes_pdf())
    (raiz / "docs" / "trabalho.docx").write_bytes(bytes_docx())
    (raiz / "notas.txt").write_text("lista de compras: arroz, feijão\n", encoding="utf-8")
    return raiz


@pytest.fixture
def indice(tmp_path: Path):
    with Indice(tmp_path / "dados" / "indice.sqlite") as i:
        yield i
