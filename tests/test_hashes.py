from faxineiro.hashes import TAMANHO_PARCIAL, Hasher

# Vetores oficiais do BLAKE3.
HASH_VAZIO = "af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262"
HASH_ABC = "6437b3ac38465133ffb63b75273a8db548c558465d79db03fd359c6cd5bd9d85"


def test_vetores_conhecidos(tmp_path):
    vazio = tmp_path / "vazio"
    vazio.write_bytes(b"")
    abc = tmp_path / "abc"
    abc.write_bytes(b"abc")
    h = Hasher()
    assert h.completo(vazio) == HASH_VAZIO
    assert h.completo(abc) == HASH_ABC
    assert h.parcial(abc) == HASH_ABC


def test_mesmo_conteudo_mesmo_hash(tmp_path):
    a, b = tmp_path / "a.bin", tmp_path / "b.bin"
    dados = bytes(range(256)) * 1000
    a.write_bytes(dados)
    b.write_bytes(dados)
    h = Hasher()
    assert h.completo(a) == h.completo(b)
    assert h.completos == 2
    assert h.bytes_lidos == 2 * len(dados)


def test_inicio_igual_fim_diferente(tmp_path):
    comum = b"x" * (TAMANHO_PARCIAL * 3)
    a, b = tmp_path / "a.bin", tmp_path / "b.bin"
    a.write_bytes(comum + b"A")
    b.write_bytes(comum + b"B")
    h = Hasher()
    assert h.parcial(a) == h.parcial(b)
    assert h.completo(a) != h.completo(b)


def test_arquivo_pequeno_parcial_igual_completo(tmp_path):
    p = tmp_path / "pequeno.txt"
    p.write_bytes(b"conteudo pequeno")
    h = Hasher()
    assert h.parcial(p) == h.completo(p)
