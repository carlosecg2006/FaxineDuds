from faxineiro.extracao import LIMITE_CARACTERES, comeco_do_texto

from .conftest import bytes_zip


def _pdf_com_texto(texto: str) -> bytes:
    """PDF mínimo de 1 página com texto (o pypdf reconstrói a tabela xref se precisar)."""
    conteudo = f"BT /F1 12 Tf 72 712 Td ({texto}) Tj ET".encode("latin-1")
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(conteudo) + conteudo + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    saida = bytearray(b"%PDF-1.4\n")
    posicoes = []
    for i, obj in enumerate(objetos, 1):
        posicoes.append(len(saida))
        saida += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    inicio_xref = len(saida)
    saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
    for p in posicoes:
        saida += b"%010d 00000 n \n" % p
    saida += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objetos) + 1, inicio_xref)
    return bytes(saida)


def test_texto_e_cortado(tmp_path):
    p = tmp_path / "longo.txt"
    p.write_text("palavra " * 2000 + "FIM_DO_ARQUIVO", encoding="utf-8")
    texto = comeco_do_texto(p, "texto")
    assert len(texto) <= LIMITE_CARACTERES
    assert "FIM_DO_ARQUIVO" not in texto


def test_texto_ansi_do_windows(tmp_path):
    p = tmp_path / "antigo.txt"
    p.write_bytes("relatório de manutenção".encode("cp1252"))
    assert comeco_do_texto(p, "texto") == "relatório de manutenção"


def test_docx(tmp_path):
    p = tmp_path / "trabalho.docx"
    p.write_bytes(bytes_zip({
        "[Content_Types].xml": b"<Types/>",
        "word/document.xml": "<w:document><w:body><w:p><w:t>Trabalho de Banco de Dados</w:t></w:p>"
                             "<w:p><w:t>Normalização &amp; SQL</w:t></w:p></w:body></w:document>".encode(),
    }))
    assert comeco_do_texto(p, "docx") == "Trabalho de Banco de Dados Normalização & SQL"


def test_xlsx(tmp_path):
    p = tmp_path / "gastos.xlsx"
    p.write_bytes(bytes_zip({
        "xl/sharedStrings.xml": b"<sst><si><t>Aluguel</t></si><si><t>Mercado</t></si></sst>",
        "xl/worksheets/sheet1.xml": b"<worksheet><c><v>1200</v></c></worksheet>",
    }))
    assert comeco_do_texto(p, "xlsx") == "Aluguel Mercado 1200"


def test_pptx(tmp_path):
    p = tmp_path / "aula.pptx"
    p.write_bytes(bytes_zip({"ppt/slides/slide1.xml": b"<p:sld><a:t>Redes de Computadores</a:t></p:sld>"}))
    assert comeco_do_texto(p, "pptx") == "Redes de Computadores"


def test_pdf(tmp_path):
    p = tmp_path / "boleto.pdf"
    p.write_bytes(_pdf_com_texto("Boleto de energia eletrica"))
    assert "Boleto de energia" in comeco_do_texto(p, "pdf")


def test_arquivo_corrompido_vira_none(tmp_path):
    p = tmp_path / "quebrado.docx"
    p.write_bytes(b"PK\x03\x04 isto nao e um zip de verdade")
    assert comeco_do_texto(p, "docx") is None
    q = tmp_path / "quebrado.pdf"
    q.write_bytes(b"%PDF-1.4 lixo")
    assert comeco_do_texto(q, "pdf") is None


def test_tipo_sem_texto(tmp_path):
    p = tmp_path / "foto.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert comeco_do_texto(p, "png") is None
