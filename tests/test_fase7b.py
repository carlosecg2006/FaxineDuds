"""Fase 7B: modo PC real (áreas de ação), quarentena por unidade, caminhos longos e
"mover para outra unidade" (cópia conferida por hash, diário e recuperação).

As duas unidades são simuladas dentro do tmp_path (`unidade=` da Quarentena); o teste com as
unidades de verdade (C: e D:) só roda com FAXINEIRO_TESTE_DUAS_UNIDADES=1.
"""

from __future__ import annotations

import os
import random
import uuid
from pathlib import Path

import pytest

from faxineiro import config, disco
from faxineiro.config import area_de, areas_de_acao, pasta_quarentena
from faxineiro.hashes import Hasher
from faxineiro.protecoes import Protecoes
from faxineiro.quarentena import ANTES_DE_MEXER, DEPOIS_DE_MEXER, Quarentena
from faxineiro.scanner import escanear
from faxineiro.transferir import COPIADO, ORIGINAL_NA_QUARENTENA, PREFIXO_TEMP, planejar_mover_unidade


class Travou(Exception):
    """Simula o app sendo fechado à força no meio da operação."""


def _bytes(semente, tamanho=3000):
    return random.Random(semente).randbytes(tamanho)


def _criar(caminho: Path, conteudo: bytes = b"x") -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(conteudo)
    return caminho


def _hash(caminho):
    return Hasher().completo(caminho)


def _muito_espaco(_):
    return 10**12


# --- áreas e modo PC real ---------------------------------------------------------------


def test_modo_pc_real_desligado_so_pasta_teste():
    assert areas_de_acao(False) == (config.PASTA_TESTE,)
    assert set(areas_de_acao(True)) == {config.PASTA_TESTE, *config.AREAS_DE_LEITURA}


def test_area_mais_especifica_ganha():
    arquivo = config.PASTA_TESTE / "Docs" / "a.txt"
    assert area_de(arquivo, areas_de_acao(True)) == config.PASTA_TESTE.resolve()
    assert area_de(Path(r"D:\Packs\x.wav"), areas_de_acao(True)) == Path("D:\\")
    assert area_de(Path(r"D:\Packs\x.wav"), areas_de_acao(False)) is None


def test_pc_real_desligado_recusa_com_aviso_claro(indice):
    """Nada no PC real sem ligar o modo; ligado, a pasta do próprio app continua proibida."""
    arquivo = config.RAIZ_PROJETO / "CLAUDE.md"
    desligado = Quarentena(indice, limite=areas_de_acao(False)).planejar_mover([arquivo])
    assert "ligue o modo PC real" in desligado.passos[0].problema
    ligado = Quarentena(indice, limite=areas_de_acao(True)).planejar_mover([arquivo])
    assert "bloqueada" in ligado.passos[0].problema
    assert arquivo.exists()


# --- quarentena por unidade ---------------------------------------------------------------


def test_quarentena_de_cada_unidade():
    assert pasta_quarentena(config.PASTA_TESTE / "a.txt") == config.PASTA_TESTE / "_quarentena"
    assert pasta_quarentena(config.PASTA_DO_USUARIO / "Downloads" / "a.txt") == config.PASTA_DO_USUARIO / "_quarentena"
    assert pasta_quarentena(Path(r"D:\Packs\a.wav")) == Path(r"D:\_quarentena")
    assert pasta_quarentena(Path(r"E:\Fotos\a.jpg")) == Path(r"E:\_quarentena")


@pytest.fixture
def duas(tmp_path, indice):
    """Duas "unidades" simuladas: tmp/C e tmp/D, cada uma com a sua quarentena."""
    c, d = tmp_path / "C", tmp_path / "D"
    _criar(c / "Musicas" / "Samples" / "kick.wav", _bytes(1))
    _criar(c / "Musicas" / "Samples" / "Loops" / "loop.wav", _bytes(2))
    _criar(c / "Musicas" / "Samples" / "Loops" / "loop2.wav", _bytes(3))
    (c / "Musicas" / "Samples" / "Vazia").mkdir()
    _criar(c / "Downloads" / "instalador.exe", _bytes(4, 5000))
    (d / "Arquivo").mkdir(parents=True)

    def unidade(caminho):
        p = Path(caminho).resolve()
        return "C:" if p == c or c in p.parents else "D:" if p == d or d in p.parents else "?"

    def local(arquivo):
        return (c if unidade(arquivo) == "C:" else d) / "_quarentena"

    escanear(c, indice)
    q = Quarentena(indice, limite=(c, d), local=local, unidade=unidade, protecoes=Protecoes(nuvem_pastas=[]))
    return q, c, d


def test_quarentena_em_duas_unidades_e_desfazer(duas, indice):
    q, c, d = duas
    em_d = _criar(d / "Arquivo" / "velho.txt", _bytes(9))
    alvos = [c / "Downloads" / "instalador.exe", em_d]
    hashes = [_hash(a) for a in alvos]
    r = q.executar(q.planejar_mover(alvos))
    assert len(r.feitos) == 2
    assert r.feitos[0].destino.is_relative_to(c / "_quarentena")
    assert r.feitos[1].destino.is_relative_to(d / "_quarentena")
    q.executar(q.planejar_desfazer(lote=r.lote_id))
    assert [_hash(a) for a in alvos] == hashes


def test_quarentena_recusa_pasta_bloco_nuvem_e_programa(tmp_path, indice):
    area = tmp_path / "area"
    projeto = _criar(area / "Projeto" / "src" / "main.py")
    _criar(area / "Projeto" / ".git" / "HEAD")
    nuvem = _criar(area / "OneDrive" / "foto.jpg")
    jogo = _criar(area / ".minecraft" / "saves" / "mundo.dat")
    solto = _criar(area / "solto.txt")
    _criar(area / ".vscode" / "settings.json")  # a raiz da área ter .vscode NÃO a torna pasta-bloco
    q = Quarentena(indice, limite=area, protecoes=Protecoes(nuvem_pastas=[]), local=lambda a: area / "_quarentena")
    plano = q.planejar_mover([projeto, nuvem, jogo, solto])
    motivos = {p.origem.name: p.problema for p in plano.passos}
    assert "pasta-bloco" in motivos["main.py"]
    assert "nuvem" in motivos["foto.jpg"]
    assert "pasta-bloco" in motivos["mundo.dat"]
    assert motivos["solto.txt"] is None


def test_esvaziar_quarentena_de_area_desligada_fica_de_fora(duas, indice):
    q, c, d = duas
    q.executar(q.planejar_mover([c / "Downloads" / "instalador.exe"]))
    so_d = Quarentena(indice, limite=(d,), local=q.local, unidade=q.unidade)
    plano = so_d.planejar_esvaziar()
    assert plano.validos == [] and "fora da área" in plano.passos[0].problema


# --- caminhos com mais de 260 caracteres ---------------------------------------------------


def _fundo(base: Path) -> Path:
    fundo = base
    while len(str(fundo)) < 300:
        fundo = fundo / ("pasta_de_nome_comprido_" + "x" * 20)
    disco.criar_pastas(fundo)
    with disco.abrir(fundo / "fundo.txt", "wb") as f:
        f.write(_bytes(7))
    return fundo / "fundo.txt"


@pytest.mark.skipif(os.name != "nt", reason="limite de 260 caracteres é do Windows")
def test_caminho_longo_quarentena_ida_e_volta(tmp_path, indice):
    area = tmp_path / "area"
    area.mkdir()
    arquivo = _fundo(area)
    p = escanear(area, indice)
    assert indice.buscar(str(arquivo)) is not None, p.avisos  # o scanner agora indexa
    q = Quarentena(indice, limite=area, local=lambda a: area / "_quarentena")
    antes = _hash(arquivo)
    r = q.executar(q.planejar_mover([arquivo]))
    assert not r.falhas and not disco.existe(arquivo)
    assert len(str(r.feitos[0].destino)) > 260
    q.executar(q.planejar_desfazer(lote=r.lote_id))
    assert _hash(arquivo) == antes


@pytest.mark.skipif(os.name != "nt", reason="limite de 260 caracteres é do Windows")
def test_caminho_longo_mover_de_unidade(duas, indice):
    q, c, d = duas
    arquivo = _fundo(c / "Fundo")
    r = q.executar(planejar_mover_unidade(q, [c / "Fundo"], d / "Arquivo", espaco_livre=_muito_espaco))
    assert not r.falhas, r.falhas
    copia = d / "Arquivo" / arquivo.relative_to(c)
    assert disco.eh_arquivo(copia) and not disco.existe(arquivo)


def test_conversor_recusa_caminho_longo(tmp_path):
    from faxineiro.conversor import ConversaoRecusada, planejar_conversao
    area = tmp_path / "area"
    fundo = area / ("p" * 120) / ("q" * 100) / "foto.png"
    with pytest.raises(ConversaoRecusada, match="caminho longo demais"):
        planejar_conversao(fundo, "jpg", limite=area)


# --- mover para outra unidade: prévia ---------------------------------------------------------


def test_previa_nao_muda_nada_e_avisa(duas):
    q, c, d = duas
    plano = planejar_mover_unidade(q, [c / "Musicas" / "Samples"], d / "Arquivo", espaco_livre=_muito_espaco)
    arquivos = [p for p in plano.validos if not p.remover_pasta]
    assert len(arquivos) == 3 and plano.total_bytes == 9000
    assert not (d / "Arquivo" / "Samples").exists()
    texto = " ".join(plano.avisos)
    assert "ESVAZIAR" in texto and "FL Studio" in texto and "pasta(s) vazia(s)" in texto
    assert "Espaço no D:" in plano.avisos[0]


def test_previa_recusa_sem_espaco(duas):
    q, c, d = duas
    plano = planejar_mover_unidade(q, [c / "Downloads" / "instalador.exe"], d / "Arquivo",
                                   espaco_livre=lambda _: 10_000, folga=6_000)
    assert plano.validos == []
    assert "sem espaço" in plano.passos[0].problema
    assert plano.avisos[0].startswith("NÃO CABE")


def test_previa_recusa_mesma_unidade_destino_fora_e_pasta_bloco(duas, tmp_path):
    q, c, d = duas
    _criar(c / "Projeto" / "package.json")
    _criar(c / "Projeto" / "index.js")
    mesma = planejar_mover_unidade(q, [c / "Downloads" / "instalador.exe"], c / "Musicas", espaco_livre=_muito_espaco)
    assert "mesma unidade" in mesma.passos[0].problema
    fora = tmp_path / "fora"
    fora.mkdir()
    longe = planejar_mover_unidade(q, [c / "Downloads" / "instalador.exe"], fora, espaco_livre=_muito_espaco)
    assert "fora da área" in longe.passos[0].problema
    bloco = planejar_mover_unidade(q, [c / "Projeto"], d / "Arquivo", espaco_livre=_muito_espaco)
    assert "pasta-bloco" in bloco.passos[0].problema


def test_nome_ja_existe_no_destino_ganha_numero(duas):
    q, c, d = duas
    _criar(d / "Arquivo" / "instalador.exe", b"outro")
    plano = planejar_mover_unidade(q, [c / "Downloads" / "instalador.exe"], d / "Arquivo", espaco_livre=_muito_espaco)
    assert plano.validos[0].destino.name == "instalador (2).exe"
    q.executar(plano)
    assert (d / "Arquivo" / "instalador.exe").read_bytes() == b"outro"  # nunca sobrescreve


# --- mover para outra unidade: executar e desfazer ---------------------------------------------


def test_mover_arquivo(duas, indice):
    q, c, d = duas
    origem = c / "Downloads" / "instalador.exe"
    antes = _hash(origem)
    r = q.executar(planejar_mover_unidade(q, [origem], d / "Arquivo", espaco_livre=_muito_espaco))
    assert len(r.feitos) == 1 and not r.falhas
    copia = d / "Arquivo" / "instalador.exe"
    assert _hash(copia) == antes and not origem.exists()
    assert not any(p.name.startswith(PREFIXO_TEMP) for p in (d / "Arquivo").iterdir())
    item = indice.itens_na_quarentena()[0]  # o original está na quarentena da unidade DELE
    assert Path(item["destino"]).is_relative_to(c / "_quarentena") and item["hash_completo"] == antes
    assert indice.buscar(str(origem)) is None and indice.buscar(str(copia)) is not None
    assert os.stat(copia).st_mtime_ns == os.stat(item["destino"]).st_mtime_ns  # mantém a data


def test_mover_pasta_inteira_e_desfazer(duas, indice):
    q, c, d = duas
    pasta = c / "Musicas" / "Samples"
    hashes = {p.relative_to(c): _hash(p) for p in pasta.rglob("*.wav")}
    r = q.executar(planejar_mover_unidade(q, [pasta], d / "Arquivo", espaco_livre=_muito_espaco))
    assert not r.falhas
    assert _hash(d / "Arquivo" / "Samples" / "Loops" / "loop2.wav") == hashes[Path("Musicas/Samples/Loops/loop2.wav")]
    assert not (pasta / "Loops").exists()  # a mudança esvaziou e removeu
    assert (pasta / "Vazia").is_dir()  # já estava vazia: fica (e a de cima também)

    q.executar(q.planejar_desfazer(lote=r.lote_id))
    assert {p.relative_to(c): _hash(p) for p in pasta.rglob("*.wav")} == hashes
    assert not (d / "Arquivo" / "Samples").exists()  # pastas que a mudança criou somem
    copias = [Path(o["destino"]) for o in indice.itens_na_quarentena()]
    assert len(copias) == 3 and all(p.is_relative_to(d / "_quarentena") for p in copias)  # nada apagado
    assert indice.itens_desfaziveis(lote=r.lote_id) == []


def test_desfazer_o_item_do_original_desfaz_a_mudanca(duas, indice):
    q, c, d = duas
    origem = c / "Downloads" / "instalador.exe"
    q.executar(planejar_mover_unidade(q, [origem], d / "Arquivo", espaco_livre=_muito_espaco))
    item = indice.itens_na_quarentena()[0]
    plano = q.planejar_desfazer(item=item["id"])
    assert len(plano.validos) == 2 and any("cópia" in a for a in plano.avisos)
    q.executar(plano)
    assert origem.exists() and not (d / "Arquivo" / "instalador.exe").exists()


def test_esvaziar_o_original_torna_a_mudanca_definitiva(duas, indice):
    q, c, d = duas
    q.executar(planejar_mover_unidade(q, [c / "Downloads" / "instalador.exe"], d / "Arquivo",
                                      espaco_livre=_muito_espaco))
    r = q.executar(q.planejar_esvaziar())
    assert len(r.feitos) == 1
    assert indice.itens_desfaziveis() == []  # a cópia virou a única: não dá para "desfazer" mais
    assert (d / "Arquivo" / "instalador.exe").exists()


def test_hash_da_copia_diferente_volta_tudo(duas, indice, monkeypatch):
    q, c, d = duas
    origem = c / "Downloads" / "instalador.exe"
    antes = _hash(origem)
    real = q.hasher.completo
    monkeypatch.setattr(q.hasher, "completo",
                        lambda p: "estragado" if Path(p).name.startswith(PREFIXO_TEMP) else real(p))
    r = q.executar(planejar_mover_unidade(q, [origem], d / "Arquivo", espaco_livre=_muito_espaco))
    assert r.falhas and "não bateu" in r.falhas[0][1]
    assert _hash(origem) == antes and list((d / "Arquivo").iterdir()) == []
    op = indice.con.execute("SELECT * FROM operacoes WHERE tipo = 'mover_unidade'").fetchone()
    assert op["estado"] == "falhou" and "nada mudou" in op["erro"]
    assert indice.itens_na_quarentena() == []


def test_cancelar_no_meio_da_copia(duas, indice):
    q, c, d = duas
    grande = _criar(c / "Videos" / "grande.mp4", _bytes(5, 3 * 1024 * 1024))
    blocos = iter(range(100))
    r = q.executar(planejar_mover_unidade(q, [grande], d / "Arquivo", espaco_livre=_muito_espaco),
                   parar=lambda: next(blocos) >= 2)  # deixa começar e cancela no 2º bloco
    assert r.cancelado and grande.exists()
    assert list((d / "Arquivo").iterdir()) == []
    assert not (c / "_quarentena").exists() or not any((c / "_quarentena").rglob("*.mp4"))


@pytest.mark.skipif(os.name != "nt", reason="arquivo travado é comportamento do Windows")
def test_arquivo_em_uso_nada_muda(duas, indice):
    q, c, d = duas
    origem = c / "Downloads" / "instalador.exe"
    with open(origem, "rb"):  # aberto: o Windows não deixa renomear
        r = q.executar(planejar_mover_unidade(q, [origem], d / "Arquivo", espaco_livre=_muito_espaco))
    assert r.falhas and "em uso" in r.falhas[0][1]
    assert origem.exists() and list((d / "Arquivo").iterdir()) == []


@pytest.mark.parametrize("momento", [ANTES_DE_MEXER, ORIGINAL_NA_QUARENTENA, COPIADO])
def test_travou_antes_de_terminar_volta_tudo(duas, indice, momento):
    q, c, d = duas
    origem = c / "Downloads" / "instalador.exe"
    antes = _hash(origem)

    def gancho(m, passo):
        if m == momento:
            raise Travou()

    q.gancho = gancho
    with pytest.raises(Travou):
        q.executar(planejar_mover_unidade(q, [origem], d / "Arquivo", espaco_livre=_muito_espaco))
    q2 = Quarentena(indice, limite=q.areas, local=q.local, unidade=q.unidade)
    mensagens = q2.recuperar_diario()
    assert any("nada mudou" in m for m in mensagens), mensagens
    assert _hash(origem) == antes
    assert list((d / "Arquivo").iterdir()) == []  # nem cópia, nem temporário
    assert indice.operacoes_em_andamento() == []


def test_travou_depois_de_copiar_termina_a_mudanca(duas, indice):
    q, c, d = duas
    origem = c / "Downloads" / "instalador.exe"
    antes = _hash(origem)

    def gancho(m, passo):
        if m == DEPOIS_DE_MEXER:
            raise Travou()

    q.gancho = gancho
    with pytest.raises(Travou):
        q.executar(planejar_mover_unidade(q, [origem], d / "Arquivo", espaco_livre=_muito_espaco))
    mensagens = Quarentena(indice, limite=q.areas, local=q.local, unidade=q.unidade).recuperar_diario()
    assert any("Concluída" in m for m in mensagens), mensagens
    assert _hash(d / "Arquivo" / "instalador.exe") == antes
    assert len(indice.itens_na_quarentena()) == 1  # o original, pronto para desfazer ou esvaziar


# --- unidades de verdade (opcional) ---------------------------------------------------------


@pytest.mark.skipif(os.environ.get("FAXINEIRO_TESTE_DUAS_UNIDADES") != "1" or os.name != "nt",
                    reason="usa o C: (tmp_path) e o D: (pasta_teste) de verdade; ligue com FAXINEIRO_TESTE_DUAS_UNIDADES=1")
def test_unidades_de_verdade_c_e_d(tmp_path, indice):
    """Cópia real entre volumes diferentes: tmp_path fica no C:, a pasta_teste no D:."""
    assert tmp_path.drive.upper() != config.PASTA_TESTE.drive.upper()
    origem = _criar(tmp_path / "area" / "Samples" / "som.wav", _bytes(11, 200_000))
    destino = config.PASTA_TESTE / "_testes_7b" / uuid.uuid4().hex[:8]
    destino.mkdir(parents=True)
    q = Quarentena(indice, limite=(tmp_path / "area", config.PASTA_TESTE),
                   local=lambda a: (tmp_path / "area" / "_quarentena") if Path(a).drive.upper() == tmp_path.drive.upper()
                   else config.PASTA_TESTE / "_quarentena")
    antes = _hash(origem)
    r = q.executar(planejar_mover_unidade(q, [origem.parent], destino))
    assert not r.falhas, r.falhas
    assert _hash(destino / "Samples" / "som.wav") == antes
    q.executar(q.planejar_desfazer(lote=r.lote_id))
    assert _hash(origem) == antes and not (destino / "Samples").exists()
