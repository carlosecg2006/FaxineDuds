"""Detecta o tipo real de um arquivo pelo conteúdo (primeiros bytes), não pela extensão."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import puremagic

TAMANHO_CABECALHO = 8192

_CATEGORIAS: dict[str, tuple[str, ...]] = {
    "imagem": ("png", "jpg", "gif", "bmp", "tif", "webp", "ico", "heic", "avif", "psd"),
    "documento": ("pdf", "docx", "xlsx", "pptx", "doc", "xls", "ppt", "odt", "ods", "odp", "rtf", "epub"),
    "audio": ("mp3", "wav", "flac", "ogg", "m4a", "aac", "wma", "opus"),
    "video": ("mp4", "mkv", "avi", "mov", "wmv", "webm", "flv", "3gp", "m4v"),
    "compactado": ("zip", "rar", "7z", "gz", "bz2", "xz", "tar", "iso", "cab"),
    "executavel": ("exe", "dll", "msi"),
    "texto": ("texto",),
}
_CATEGORIA_POR_TIPO = {t: cat for cat, tipos in _CATEGORIAS.items() for t in tipos}

# Extensões que aceitamos como "conferindo" com o tipo detectado.
_SINONIMOS: dict[str, set[str]] = {
    "jpg": {"jpg", "jpeg", "jpe", "jfif"},
    "tif": {"tif", "tiff"},
    "mp4": {"mp4", "m4v"},
    "m4a": {"m4a", "mp4"},
    "mov": {"mov", "qt"},
    # EXE e DLL têm a mesma assinatura ("MZ"): pelo conteúdo não dá para separar.
    "exe": {"exe", "com", "scr", "dll", "sys", "ocx", "cpl", "drv"},
    "dll": {"dll", "sys", "ocx"},
    "doc": {"doc", "xls", "ppt", "msi", "msg"},  # formato OLE antigo compartilhado
    "xls": {"doc", "xls", "ppt", "msi", "msg"},
    "ppt": {"doc", "xls", "ppt", "msi", "msg"},
    "msi": {"doc", "xls", "ppt", "msi", "msg"},
    "zip": {"zip", "jar", "apk", "odt", "ods", "odp", "epub", "cbz", "xpi"},
    "gz": {"gz", "tgz"},
    "texto": {"txt", "md", "csv", "tsv", "log", "json", "xml", "html", "htm", "css", "js", "ts",
              "py", "java", "c", "h", "cpp", "cs", "ini", "cfg", "toml", "yaml", "yml", "bat",
              "ps1", "sh", "sql", "srt", "svg", "rtf", "tex", ""},
}

_OOXML = (
    (b"wordprocessingml", "docx"),
    (b"spreadsheetml", "xlsx"),
    (b"presentationml", "pptx"),
)
_CONTENT_TYPE_MAIN = re.compile(rb'ContentType="([^"]*main\+xml)"')


@dataclass(frozen=True)
class TipoDetectado:
    tipo_real: str        # ex.: "png", "pdf", "texto", "vazio", "desconhecido"
    categoria: str        # imagem, documento, audio, video, compactado, executavel, texto, outro
    extensao_confere: bool


_APELIDOS = {"jpeg": "jpg", "jpe": "jpg", "jfif": "jpg", "tiff": "tif", "htm": "html"}
# O puremagic às vezes reconhece texto (BOM, cabeçalho XML/HTML); tratamos tudo como "texto".
_MAGICO_TEXTO = {"txt", "csv", "xml", "html", "json", "svg", "md"}


def _normalizar_extensao(ext: str) -> str:
    ext = ext.lower().lstrip(".")
    return _APELIDOS.get(ext, ext)


def _tipo_ooxml(caminho: Path) -> str | None:
    """Zip com [Content_Types].xml é documento do Office (docx/xlsx/pptx)."""
    try:
        with zipfile.ZipFile(caminho) as z:
            dados = z.read("[Content_Types].xml")
    except (zipfile.BadZipFile, KeyError, OSError, RuntimeError):
        return None
    for main in _CONTENT_TYPE_MAIN.findall(dados):
        for marcador, tipo in _OOXML:
            if marcador in main:
                return tipo
    return None


def _parece_texto(cabecalho: bytes) -> bool:
    if b"\x00" in cabecalho:
        # UTF-16 com BOM tem bytes zero, mas é texto.
        return cabecalho.startswith((b"\xff\xfe", b"\xfe\xff"))
    try:
        cabecalho.decode("utf-8")
        return True
    except UnicodeDecodeError as erro:
        # Corte no meio de um caractere de vários bytes no fim do cabeçalho.
        if erro.start >= len(cabecalho) - 3:
            return True
    # Latin-1 decodifica qualquer coisa; exige que quase tudo seja imprimível.
    imprimiveis = sum(32 <= b < 127 or b in (9, 10, 13) or b >= 160 for b in cabecalho)
    return imprimiveis / len(cabecalho) > 0.95


def _tipo_magico(cabecalho: bytes) -> str | None:
    try:
        resultados = puremagic.magic_string(cabecalho)  # sem nome: a extensão não influencia
    except (puremagic.PureError, ValueError):
        return None
    for r in resultados:
        if r.extension:
            tipo = _normalizar_extensao(r.extension)
            return "texto" if tipo in _MAGICO_TEXTO else tipo
    return None


def detectar_tipo(caminho: str | Path) -> TipoDetectado:
    """Lê o começo do arquivo e devolve o tipo real, a categoria e se a extensão confere."""
    caminho = Path(caminho)
    extensao = _normalizar_extensao(caminho.suffix)

    with open(caminho, "rb") as f:
        cabecalho = f.read(TAMANHO_CABECALHO)

    if not cabecalho:
        return TipoDetectado("vazio", "outro", True)

    tipo = _tipo_magico(cabecalho)
    if tipo == "zip" or cabecalho.startswith(b"PK\x03\x04"):
        tipo = _tipo_ooxml(caminho) or "zip"
    if tipo is None:
        tipo = "texto" if _parece_texto(cabecalho) else "desconhecido"

    categoria = _CATEGORIA_POR_TIPO.get(tipo, "outro")
    return TipoDetectado(tipo, categoria, extensao_confere(tipo, extensao))


def extensao_confere(tipo_real: str, extensao: str) -> bool:
    """A extensão combina com o conteúdo?

    Só acusa quando dá para julgar: se o tipo é desconhecido/vazio, ou se a extensão
    não é de nenhum formato que conhecemos (.tmp, .bin, .db, .crdownload...), não acusa.
    """
    extensao = _normalizar_extensao(extensao)
    if tipo_real in ("desconhecido", "vazio") or extensao not in _EXTENSOES_CONHECIDAS:
        return True
    return extensao in _SINONIMOS.get(tipo_real, {tipo_real})


_EXTENSOES_CONHECIDAS: set[str] = (
    set(_CATEGORIA_POR_TIPO) - {"texto"}
) | {ext for aceitas in _SINONIMOS.values() for ext in aceitas}
