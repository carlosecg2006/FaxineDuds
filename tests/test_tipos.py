import os

from faxineiro.tipos import detectar_tipo

from .conftest import bytes_docx, bytes_jpeg, bytes_pdf, bytes_png, bytes_zip


def test_png(tmp_path):
    p = tmp_path / "foto.png"
    p.write_bytes(bytes_png())
    t = detectar_tipo(p)
    assert (t.tipo_real, t.categoria, t.extensao_confere) == ("png", "imagem", True)


def test_jpeg_com_extensao_jpeg(tmp_path):
    p = tmp_path / "foto.JPEG"
    p.write_bytes(bytes_jpeg())
    t = detectar_tipo(p)
    assert (t.tipo_real, t.extensao_confere) == ("jpg", True)


def test_pdf(tmp_path):
    p = tmp_path / "doc.pdf"
    p.write_bytes(bytes_pdf())
    t = detectar_tipo(p)
    assert (t.tipo_real, t.categoria) == ("pdf", "documento")


def test_docx_nao_e_confundido_com_zip(tmp_path):
    p = tmp_path / "trabalho.docx"
    p.write_bytes(bytes_docx())
    t = detectar_tipo(p)
    assert (t.tipo_real, t.categoria, t.extensao_confere) == ("docx", "documento", True)


def test_zip_comum(tmp_path):
    p = tmp_path / "pacote.zip"
    p.write_bytes(bytes_zip({"a.txt": b"oi"}))
    t = detectar_tipo(p)
    assert (t.tipo_real, t.categoria, t.extensao_confere) == ("zip", "compactado", True)


def test_extensao_mentirosa(tmp_path):
    """Um PNG renomeado para .jpg é detectado pelo conteúdo."""
    p = tmp_path / "falso.jpg"
    p.write_bytes(bytes_png())
    t = detectar_tipo(p)
    assert t.tipo_real == "png"
    assert t.extensao_confere is False


def test_pdf_sem_extensao(tmp_path):
    p = tmp_path / "sem_extensao"
    p.write_bytes(bytes_pdf())
    t = detectar_tipo(p)
    assert t.tipo_real == "pdf"
    assert t.extensao_confere is False


def test_extensao_desconhecida_nao_e_acusada(tmp_path):
    """.tmp/.db/.bin não têm formato fixo: não dá para dizer que estão erradas."""
    for nome in ("cache.tmp", "Thumbs.db", "dados.bin", "x.crdownload"):
        p = tmp_path / nome
        p.write_text("qualquer coisa", encoding="utf-8")
        assert detectar_tipo(p).extensao_confere is True, nome


def test_dll_nao_e_extensao_errada():
    from faxineiro.tipos import extensao_confere

    assert extensao_confere("exe", "dll")  # DLL e EXE têm a mesma assinatura MZ


def test_texto_utf8(tmp_path):
    p = tmp_path / "notas.txt"
    p.write_text("Olá, acentuação ç ã é\n" * 50, encoding="utf-8")
    t = detectar_tipo(p)
    assert (t.tipo_real, t.categoria, t.extensao_confere) == ("texto", "texto", True)


def test_texto_utf16(tmp_path):
    p = tmp_path / "windows.txt"
    p.write_text("relatório do bloco de notas", encoding="utf-16")
    assert detectar_tipo(p).tipo_real == "texto"


def test_binario_aleatorio(tmp_path):
    p = tmp_path / "lixo.bin"
    p.write_bytes(b"\x00\x01\x02\x03" + os.urandom(2000))
    t = detectar_tipo(p)
    assert t.tipo_real == "desconhecido"
    assert t.categoria == "outro"


def test_arquivo_vazio(tmp_path):
    p = tmp_path / "vazio.txt"
    p.write_bytes(b"")
    t = detectar_tipo(p)
    assert (t.tipo_real, t.extensao_confere) == ("vazio", True)
