import os
import random
from pathlib import Path

import pytest

from faxineiro.hashes import Hasher
from faxineiro.quarentena import (
    ANTES_DE_MEXER,
    DEPOIS_DE_MEXER,
    OperacaoRecusada,
    Quarentena,
)
from faxineiro.scanner import escanear


class Travou(Exception):
    """Simula o app sendo fechado à força no meio da operação."""


def _bytes(semente, tamanho=3000):
    return random.Random(semente).randbytes(tamanho)


@pytest.fixture
def area(tmp_path):
    """Área permitida (faz o papel da pasta_teste) com arquivos e duplicados."""
    raiz = tmp_path / "pasta_teste"
    (raiz / "Fotos").mkdir(parents=True)
    (raiz / "Docs").mkdir()
    (raiz / "Fotos" / "praia.jpg").write_bytes(_bytes(1))
    (raiz / "Fotos" / "praia - Cópia.jpg").write_bytes(_bytes(1))
    (raiz / "Docs" / "praia (2).jpg").write_bytes(_bytes(1))
    (raiz / "Docs" / "contrato.pdf").write_bytes(_bytes(2))
    (raiz / "Docs" / "notas.txt").write_text("anotações", encoding="utf-8")
    return raiz


@pytest.fixture
def q(area, indice):
    escanear(area, indice)
    return Quarentena(indice, limite=area, local=lambda arq: area / "_quarentena")


def _hash(caminho):
    return Hasher().completo(caminho)


# --- mover ---------------------------------------------------------------------


def test_previa_nao_move_nada(q, area):
    plano = q.planejar_mover([area / "Docs" / "contrato.pdf"])
    assert len(plano.validos) == 1
    assert plano.total_bytes == 3000
    assert (area / "Docs" / "contrato.pdf").exists()
    assert not (area / "_quarentena").exists()


def test_mover_para_quarentena(q, area, indice):
    alvo = area / "Docs" / "contrato.pdf"
    hash_antes = _hash(alvo)
    r = q.executar(q.planejar_mover([alvo]))
    assert len(r.feitos) == 1 and not r.falhas
    assert not alvo.exists()
    destino = r.feitos[0].destino
    assert destino.exists()
    assert destino.is_relative_to(area / "_quarentena" / f"{r.lote_id:04d}")
    assert destino.name == "contrato.pdf"
    assert _hash(destino) == hash_antes
    # histórico
    item = indice.itens_na_quarentena()[0]
    assert item["origem"] == str(alvo)
    assert item["hash_completo"] == hash_antes
    assert item["estado"] == "feita" and item["situacao"] == "na_quarentena"
    assert item["criado_em"]
    # saiu do índice
    assert indice.buscar(str(alvo)) is None


def test_mover_nao_copia_mesmo_inode(q, area):
    alvo = area / "Docs" / "contrato.pdf"
    inode = alvo.stat().st_ino
    r = q.executar(q.planejar_mover([alvo]))
    assert r.feitos[0].destino.stat().st_ino == inode  # renomeado, não copiado


def test_recusa_fora_da_area(q, tmp_path):
    fora = tmp_path / "fora.txt"
    fora.write_text("não me toque", encoding="utf-8")
    plano = q.planejar_mover([fora])
    assert plano.validos == []
    assert "fora da área" in plano.passos[0].problema
    assert q.executar(plano).feitos == []
    assert fora.exists()


def test_recusa_outra_unidade(indice, area):
    escanear(area, indice)
    q = Quarentena(indice, limite=area, local=lambda arq: Path("Z:/_quarentena"))
    plano = q.planejar_mover([area / "Docs" / "contrato.pdf"])
    assert plano.validos == []
    assert "outra unidade" in plano.passos[0].problema


def test_recusa_se_arquivo_mudou_depois_da_previa(q, area, indice):
    alvo = area / "Docs" / "contrato.pdf"
    # simula hash conhecido no índice e o arquivo mudando depois
    plano = q.planejar_mover([alvo])
    plano.passos[0].hash_esperado = "0" * 64
    r = q.executar(plano)
    assert r.feitos == [] and "mudou" in r.falhas[0][1]
    assert alvo.exists()


# --- desfazer -------------------------------------------------------------------


def test_desfazer_item_confere_hash_e_volta_ao_indice(q, area, indice):
    alvo = area / "Docs" / "contrato.pdf"
    hash_antes = _hash(alvo)
    q.executar(q.planejar_mover([alvo]))
    item = indice.itens_na_quarentena()[0]
    r = q.executar(q.planejar_desfazer(item=item["id"]))
    assert len(r.feitos) == 1 and not r.falhas
    assert alvo.exists() and _hash(alvo) == hash_antes
    assert indice.buscar(str(alvo)) is not None
    assert indice.itens_na_quarentena() == []
    assert indice.operacao(item["id"])["situacao"] == "restaurado"


def test_desfazer_lote_inteiro_recria_pasta(q, area, indice):
    alvos = [area / "Docs" / "contrato.pdf", area / "Docs" / "notas.txt", area / "Docs" / "praia (2).jpg"]
    r = q.executar(q.planejar_mover(alvos))
    assert not any(a.exists() for a in alvos)
    os.rmdir(area / "Docs")  # a pasta original ficou vazia e foi apagada
    r2 = q.executar(q.planejar_desfazer(lote=r.lote_id))
    assert len(r2.feitos) == 3
    assert all(a.exists() for a in alvos)
    assert not (area / "_quarentena" / f"{r.lote_id:04d}").exists()  # pastas vazias limpas


def test_desfazer_recusa_arquivo_adulterado(q, area, indice):
    alvo = area / "Docs" / "contrato.pdf"
    r = q.executar(q.planejar_mover([alvo]))
    r.feitos[0].destino.write_bytes(b"adulterado")
    r2 = q.executar(q.planejar_desfazer(lote=r.lote_id))
    assert r2.feitos == [] and "hash" in r2.falhas[0][1]
    assert not alvo.exists()
    assert r.feitos[0].destino.exists()  # nada foi apagado


# --- conflito de nome --------------------------------------------------------------


def test_conflito_renomeia_e_nunca_sobrescreve(q, area):
    alvo = area / "Docs" / "notas.txt"
    r = q.executar(q.planejar_mover([alvo]))
    alvo.write_text("arquivo novo com o mesmo nome", encoding="utf-8")
    plano = q.planejar_desfazer(lote=r.lote_id, conflito="renomear")
    assert plano.passos[0].destino.name == "notas (restaurado).txt"
    q.executar(plano)
    assert alvo.read_text(encoding="utf-8") == "arquivo novo com o mesmo nome"
    assert (area / "Docs" / "notas (restaurado).txt").read_text(encoding="utf-8") == "anotações"


def test_conflito_pular(q, area, indice):
    alvo = area / "Docs" / "notas.txt"
    r = q.executar(q.planejar_mover([alvo]))
    alvo.write_text("novo", encoding="utf-8")
    plano = q.planejar_desfazer(lote=r.lote_id, conflito="pular")
    assert plano.validos == [] and "já existe" in plano.passos[0].problema
    q.executar(plano)
    assert alvo.read_text(encoding="utf-8") == "novo"
    assert len(indice.itens_na_quarentena()) == 1  # continua na quarentena


def test_conflito_pergunta_ao_usuario(q, area):
    alvo = area / "Docs" / "notas.txt"
    r = q.executar(q.planejar_mover([alvo]))
    alvo.write_text("novo", encoding="utf-8")
    perguntas = []
    plano = q.planejar_desfazer(lote=r.lote_id, conflito=lambda c: perguntas.append(c) or "renomear")
    assert perguntas == [alvo]
    assert plano.passos[0].renomeado


def test_conflito_dois_restaurados_com_mesmo_nome(q, area):
    alvo = area / "Docs" / "notas.txt"
    r1 = q.executar(q.planejar_mover([alvo]))
    alvo.write_text("segunda versão", encoding="utf-8")
    r2 = q.executar(q.planejar_mover([alvo]))
    alvo.write_text("terceira", encoding="utf-8")
    q.executar(q.planejar_desfazer(lote=r1.lote_id))
    q.executar(q.planejar_desfazer(lote=r2.lote_id))
    nomes = sorted(p.name for p in (area / "Docs").glob("notas*"))
    assert nomes == ["notas (restaurado 2).txt", "notas (restaurado).txt", "notas.txt"]


# --- travamento simulado -----------------------------------------------------------


def _quarentena_que_trava(indice, area, momento):
    def gancho(m, passo):
        if m == momento:
            raise Travou()

    return Quarentena(indice, limite=area, local=lambda arq: area / "_quarentena", gancho=gancho)


def test_travou_antes_de_mover(area, indice):
    escanear(area, indice)
    alvo = area / "Docs" / "contrato.pdf"
    q = _quarentena_que_trava(indice, area, ANTES_DE_MEXER)
    with pytest.raises(Travou):
        q.executar(q.planejar_mover([alvo]))
    assert indice.operacoes_em_andamento()  # o diário mostra a operação pela metade
    # app aberto de novo:
    q2 = Quarentena(indice, limite=area, local=lambda arq: area / "_quarentena")
    mensagens = q2.recuperar_diario()
    assert "nada mudou" in mensagens[0]
    assert alvo.exists()
    assert indice.operacoes_em_andamento() == []
    assert indice.itens_na_quarentena() == []


def test_travou_depois_de_mover(area, indice):
    escanear(area, indice)
    alvo = area / "Docs" / "contrato.pdf"
    q = _quarentena_que_trava(indice, area, DEPOIS_DE_MEXER)
    with pytest.raises(Travou):
        q.executar(q.planejar_mover([alvo]))
    assert not alvo.exists()
    q2 = Quarentena(indice, limite=area, local=lambda arq: area / "_quarentena")
    mensagens = q2.recuperar_diario()
    assert "Concluída" in mensagens[0]
    itens = indice.itens_na_quarentena()
    assert len(itens) == 1 and Path(itens[0]["destino"]).exists()
    assert indice.buscar(str(alvo)) is None
    # e dá para desfazer normalmente depois da recuperação
    q2.executar(q2.planejar_desfazer(item=itens[0]["id"]))
    assert alvo.exists()


def test_travou_no_meio_do_desfazer(q, area, indice):
    alvo = area / "Docs" / "contrato.pdf"
    r = q.executar(q.planejar_mover([alvo]))
    qt = _quarentena_que_trava(indice, area, DEPOIS_DE_MEXER)
    with pytest.raises(Travou):
        qt.executar(qt.planejar_desfazer(lote=r.lote_id))
    q.recuperar_diario()
    assert alvo.exists()
    assert indice.itens_na_quarentena() == []
    assert indice.buscar(str(alvo)) is not None


def test_travou_no_meio_do_esvaziar(q, area, indice):
    r = q.executar(q.planejar_mover([area / "Docs" / "contrato.pdf"]))
    qt = _quarentena_que_trava(indice, area, ANTES_DE_MEXER)
    with pytest.raises(Travou):
        qt.executar(qt.planejar_esvaziar())
    mensagens = q.recuperar_diario()
    assert "nada foi apagado" in mensagens[0]
    assert r.feitos[0].destino.exists()
    assert len(indice.itens_na_quarentena()) == 1


# --- duplicados do Raio-X ------------------------------------------------------------


def test_duplicados_mantem_o_sugerido(q, area, indice):
    plano = q.planejar_duplicados(area)
    assert len(plano.validos) == 2
    mantido = plano.validos[0].manter
    r = q.executar(plano)
    assert len(r.feitos) == 2
    assert mantido.exists()
    restantes = [p for p in area.rglob("*praia*") if "_quarentena" not in p.parts]
    assert restantes == [mantido]


def test_duplicados_nao_move_se_o_mantido_sumiu(q, area):
    plano = q.planejar_duplicados(area)
    mantido = plano.validos[0].manter
    mantido.rename(mantido.with_suffix(".sumiu"))  # alguém mexeu entre a prévia e a execução
    r = q.executar(plano)
    assert r.feitos == []
    assert all("sumiu" in msg for _, msg in r.falhas)


def test_duplicados_nao_move_se_o_mantido_mudou(q, area):
    plano = q.planejar_duplicados(area)
    plano.validos[0].manter.write_bytes(_bytes(99))
    r = q.executar(plano)
    assert r.feitos == []
    assert all("não é mais igual" in msg for _, msg in r.falhas)


# --- esvaziar ----------------------------------------------------------------------


def test_esvaziar_apaga_so_o_historico(q, area, indice):
    r = q.executar(q.planejar_mover([area / "Docs" / "contrato.pdf", area / "Docs" / "notas.txt"]))
    estranho = area / "_quarentena" / "nao_e_do_historico.txt"
    estranho.write_text("fiquei", encoding="utf-8")
    plano = q.planejar_esvaziar()
    assert plano.total_bytes == 3000 + len("anotações".encode("utf-8"))
    r2 = q.executar(plano)
    assert len(r2.feitos) == 2
    assert not any(p.destino.exists() for p in r.feitos)
    assert estranho.exists()
    assert indice.itens_na_quarentena() == []
    situacoes = {l[0] for l in indice.con.execute("SELECT situacao FROM operacoes WHERE tipo='quarentena'")}
    assert situacoes == {"esvaziado"}
    # pastas de lote vazias foram removidas
    assert not (area / "_quarentena" / f"{r.lote_id:04d}").exists()


def test_esvaziar_nao_apaga_restaurados(q, area, indice):
    r = q.executar(q.planejar_mover([area / "Docs" / "contrato.pdf"]))
    q.executar(q.planejar_desfazer(lote=r.lote_id))
    assert q.planejar_esvaziar().validos == []
    assert (area / "Docs" / "contrato.pdf").exists()


def test_esvaziar_nao_apaga_arquivo_adulterado(q, area):
    r = q.executar(q.planejar_mover([area / "Docs" / "contrato.pdf"]))
    r.feitos[0].destino.write_bytes(b"trocado")
    r2 = q.executar(q.planejar_esvaziar())
    assert r2.feitos == [] and "não bate" in r2.falhas[0][1]
    assert r.feitos[0].destino.exists()


def test_executar_plano_vazio_nao_cria_lote(q, indice):
    r = q.executar(q.planejar_esvaziar())
    assert r.lote_id is None
    assert indice.con.execute("SELECT COUNT(*) FROM lotes").fetchone()[0] == 0


def test_operacao_recusada_e_excecao_propria():
    assert issubclass(OperacaoRecusada, Exception)
