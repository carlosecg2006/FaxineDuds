"""Pastas-bloco, pastas da nuvem e o organizar respeitando as duas."""

from pathlib import Path

import pytest

from faxineiro.config import Bloqueios
from faxineiro.descricoes import descrever
from faxineiro.organizacao import planejar_organizacao, sugerir_pastas
from faxineiro.protecoes import Protecoes
from faxineiro.quarentena import Quarentena
from faxineiro.scanner import escanear

from .falsos import ClienteFalso


def _criar(caminho: Path, conteudo: bytes = b"x") -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(conteudo)
    return caminho


def _p(**kw):
    return Protecoes(nuvem_pastas=[], **kw)  # não depende do OneDrive real deste PC


# --- pastas-bloco ----------------------------------------------------------------------


@pytest.mark.parametrize("marcador", [
    ".git/HEAD", "package.json", "pyproject.toml", "requirements.txt", "Cargo.toml",
    "MeuApp.sln", "app.csproj", "node_modules/x.js", ".venv/pyvenv.cfg", "save1.sav",
])
def test_detecta_pasta_bloco(tmp_path, marcador):
    _criar(tmp_path / "projeto" / marcador)
    assert _p().motivo_bloco(tmp_path / "projeto")


def test_programa_com_exe_e_dlls(tmp_path):
    _criar(tmp_path / "Jogo" / "jogo.exe")
    assert _p().motivo_bloco(tmp_path / "Jogo") is None  # .exe sozinho (um instalador baixado) não é bloco
    _criar(tmp_path / "Jogo" / "engine.dll")
    assert "DLL" in _p().motivo_bloco(tmp_path / "Jogo")


def test_pasta_bloco_pelo_nome(tmp_path):
    (tmp_path / "Saved Games").mkdir()
    assert _p().motivo_bloco(tmp_path / "Saved Games")


def test_pasta_comum_nao_e_bloco(tmp_path):
    _criar(tmp_path / "Fotos" / "praia.jpg")
    _criar(tmp_path / "Fotos" / "instalador.exe")
    assert _p().motivo_bloco(tmp_path / "Fotos") is None


def test_arquivo_bem_fundo_dentro_do_bloco(tmp_path):
    _criar(tmp_path / "site" / "package.json")
    arquivo = _criar(tmp_path / "site" / "src" / "img" / "logo.png")
    pasta, motivo = _p().bloco_que_contem(arquivo, tmp_path)
    assert pasta == tmp_path / "site" and "package.json" in motivo


def test_lista_configuravel(tmp_path):
    _criar(tmp_path / "trabalho" / ".meu_marcador")
    assert _p().motivo_bloco(tmp_path / "trabalho") is None
    assert _p(marcadores=(".meu_marcador",)).motivo_bloco(tmp_path / "trabalho")


# --- nuvem -------------------------------------------------------------------------------


@pytest.mark.parametrize("caminho, servico", [
    ("C:/Users/c/OneDrive/Documentos/a.txt", "OneDrive"),
    ("C:/Users/c/OneDrive - Faculdade/a.txt", "OneDrive - Faculdade"),
    ("G:/Meu Drive/a.txt", "Meu Drive"),
    ("C:/Users/c/Google Drive/a.txt", "Google Drive"),
    ("D:/Dropbox/fotos/a.jpg", "Dropbox"),
    ("C:/Users/c/Documentos/a.txt", None),
    ("C:/Users/c/Documentos/OneDriveSetup.exe", None),  # o arquivo pode ter o nome, a pasta não
])
def test_detecta_pasta_da_nuvem(caminho, servico):
    assert _p().nuvem(Path(caminho)) == servico


def test_pasta_do_onedrive_informada_pelo_windows(tmp_path):
    onedrive = tmp_path / "Arquivos Sincronizados"
    p = Protecoes(nuvem_pastas=[str(onedrive)])
    assert p.nuvem(onedrive / "a.txt") == "Arquivos Sincronizados"


def test_variavel_onedrive(tmp_path, monkeypatch):
    monkeypatch.setenv("OneDrive", str(tmp_path / "Nuvem"))
    assert Protecoes().nuvem(tmp_path / "Nuvem" / "x.txt")


# --- o organizar respeita tudo isso ------------------------------------------------------


@pytest.fixture
def usuario(tmp_path):
    raiz = tmp_path / "pasta_teste"
    _criar(raiz / "Downloads" / "boleto_luz.pdf", b"%PDF-1.4 boleto")
    _criar(raiz / "Downloads" / "receita_bolo.txt", b"bolo de cenoura")
    _criar(raiz / "Projetos" / "meu_site" / "package.json", b"{}")
    _criar(raiz / "Projetos" / "meu_site" / "index.html", b"<html></html>")
    _criar(raiz / "Projetos" / "meu_site" / "notas soltas.txt", b"anotacoes")
    _criar(raiz / "Jogos" / "MeuJogo" / "jogo.exe", b"MZ")
    _criar(raiz / "Jogos" / "MeuJogo" / "engine.dll", b"MZ")
    _criar(raiz / "Jogos" / "MeuJogo" / "save1.sav", b"save")
    _criar(raiz / "OneDrive" / "trabalho.txt", b"relatorio")
    return raiz


def _plano(indice, raiz):
    escanear(raiz, indice)
    descrever(indice, raiz, ClienteFalso(), dormir=lambda s: None)
    sugerir_pastas(indice, raiz, ClienteFalso(pasta=lambda p: "Organizados/Geral"), protecoes=_p())
    q = Quarentena(indice, limite=raiz, local=lambda a: raiz / "_quarentena")
    return planejar_organizacao(indice, raiz, q, _p()), q


def test_organizar_so_mexe_em_arquivos_soltos(usuario, indice):
    plano, _ = _plano(indice, usuario)
    movidos = sorted(p.origem.name for p in plano.validos)
    assert movidos == ["boleto_luz.pdf", "receita_bolo.txt"]
    motivos = {a.name: m for a, m in plano.ignorados}
    assert "nuvem" in motivos["trabalho.txt"] and "apagaria da nuvem" in motivos["trabalho.txt"]
    assert "pasta-bloco meu_site" in motivos["notas soltas.txt"]
    assert "pasta-bloco MeuJogo" in motivos["save1.sav"]
    assert "pasta-bloco MeuJogo" in motivos["engine.dll"]


def test_protegidos_nem_recebem_sugestao(usuario, indice):
    escanear(usuario, indice)
    ia = ClienteFalso()
    r = sugerir_pastas(indice, usuario, ia, protecoes=_p())
    assert r.protegidos == 7
    assert not any("trabalho.txt" in p or "save1.sav" in p for p in ia.prompts)
    assert indice.buscar(str(usuario / "OneDrive" / "trabalho.txt"))["pasta_sugerida"] is None


def test_aplicar_nao_toca_nos_protegidos(usuario, indice):
    plano, q = _plano(indice, usuario)
    antes = {p: p.read_bytes() for p in usuario.rglob("*") if p.is_file() and "Downloads" not in p.parts}
    r = q.executar(plano)
    assert len(r.feitos) == 2
    for caminho, conteudo in antes.items():
        assert caminho.read_bytes() == conteudo  # nada protegido saiu do lugar


def _forcar_destino(indice, raiz, pasta):
    """Simula uma sugestão perigosa gravada no índice (2ª barreira: o plano também confere)."""
    escanear(raiz, indice)
    for nome in ("boleto_luz.pdf", "receita_bolo.txt"):
        indice.gravar_pasta_sugerida(indice.buscar(str(raiz / "Downloads" / nome))["id"], pasta)
    q = Quarentena(indice, limite=raiz, local=lambda a: raiz / "_quarentena")
    return planejar_organizacao(indice, raiz, q, _p())


def test_destino_dentro_de_pasta_bloco_e_recusado(usuario, indice):
    plano = _forcar_destino(indice, usuario, "Projetos/meu_site")
    assert plano.validos == []
    assert any("destino dentro de pasta-bloco" in m for _, m in plano.ignorados)


def test_destino_na_nuvem_e_recusado(usuario, indice):
    plano = _forcar_destino(indice, usuario, "OneDrive/Organizado")
    assert plano.validos == []
    assert any("destino em pasta da nuvem" in m for _, m in plano.ignorados)


def test_pasta_bloqueada_e_protegida(tmp_path):
    raiz = tmp_path / "u"
    arquivo = _criar(raiz / "AppData" / "config.txt")
    assert _p(bloqueios=Bloqueios()).motivo_para_nao_organizar(arquivo, raiz) == "pasta bloqueada"
