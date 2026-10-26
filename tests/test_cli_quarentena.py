"""Comandos da quarentena pela linha de comando (com a pasta_teste apontada para tmp_path)."""

from datetime import date, datetime, timedelta

import pytest

from faxineiro import cli_quarentena, config
from faxineiro.formato import ha_quanto_tempo
from faxineiro.__main__ import main
from faxineiro.indice import Indice
from faxineiro.scanner import escanear


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    area = tmp_path / "pasta_teste"
    (area / "Docs").mkdir(parents=True)
    (area / "Docs" / "a.txt").write_text("conteúdo A", encoding="utf-8")
    (area / "Docs" / "a - Cópia.txt").write_text("conteúdo A", encoding="utf-8")
    (area / "Docs" / "b.txt").write_text("conteúdo B", encoding="utf-8")
    monkeypatch.setattr(config, "PASTA_TESTE", area)
    monkeypatch.setattr(cli_quarentena, "PASTA_TESTE", area)
    monkeypatch.setattr(cli_quarentena, "dentro_da_pasta_teste",
                        lambda p: config.dentro_da_pasta_teste(p, area))
    banco = tmp_path / "i.sqlite"
    with Indice(banco) as i:
        escanear(area, i)
    return area, banco


def _respostas(monkeypatch, *respostas):
    fila = list(respostas)
    monkeypatch.setattr("builtins.input", lambda texto="": fila.pop(0))


def test_so_previa_nao_move(ambiente, capsys):
    area, banco = ambiente
    alvo = area / "Docs" / "b.txt"
    assert main(["quarentena", "mover", str(alvo), "--so-previa", "--indice", str(banco)]) == 0
    saida = capsys.readouterr().out
    assert "Prévia" in saida and "só prévia" in saida
    assert alvo.exists()


def test_mover_cancelado(ambiente, monkeypatch, capsys):
    area, banco = ambiente
    _respostas(monkeypatch, "n")
    main(["quarentena", "mover", str(area / "Docs" / "b.txt"), "--indice", str(banco)])
    assert "Cancelado" in capsys.readouterr().out
    assert (area / "Docs" / "b.txt").exists()


def test_mover_listar_desfazer(ambiente, monkeypatch, capsys):
    area, banco = ambiente
    alvo = area / "Docs" / "b.txt"
    _respostas(monkeypatch, "s")
    assert main(["quarentena", "mover", str(alvo), "--indice", str(banco)]) == 0
    assert not alvo.exists()
    main(["quarentena", "listar", "--indice", str(banco)])
    assert "Docs" in capsys.readouterr().out
    assert main(["quarentena", "desfazer", "--lote", "1", "--sim", "--indice", str(banco)]) == 0
    assert alvo.exists()


def test_listar_mostra_espaco_total_e_dias_por_lote(ambiente, capsys):
    area, banco = ambiente
    main(["quarentena", "mover", str(area / "Docs" / "b.txt"), "--sim", "--indice", str(banco)])
    main(["quarentena", "mover", str(area / "Docs" / "a.txt"), "--sim", "--indice", str(banco)])
    dez_dias_atras = (datetime.now() - timedelta(days=10)).isoformat(timespec="seconds")
    with Indice(banco) as i:  # finge que o lote 1 entrou há 10 dias
        i.con.execute("UPDATE operacoes SET concluido_em = ? WHERE lote_id = 1", (dez_dias_atras,))
        i.confirmar()
    capsys.readouterr()
    main(["quarentena", "listar", "--indice", str(banco)])
    saida = capsys.readouterr().out
    tamanho = len("conteúdo B".encode()) + len("conteúdo A".encode())
    assert "Lote 1: 1 arquivo(s)" in saida and "há 10 dias" in saida
    assert "Lote 2: 1 arquivo(s)" in saida and "hoje" in saida
    assert f"Espaço total ocupado pela quarentena: {tamanho} B em 2 arquivo(s)" in saida


def test_duplicados_pela_cli(ambiente, monkeypatch):
    area, banco = ambiente
    _respostas(monkeypatch, "s")
    assert main(["quarentena", "duplicados", str(area), "--indice", str(banco)]) == 0
    restantes = sorted(p.name for p in (area / "Docs").iterdir())
    assert len([n for n in restantes if n.startswith("a")]) == 1
    assert "b.txt" in restantes


def test_esvaziar_exige_as_duas_confirmacoes(ambiente, monkeypatch, capsys):
    area, banco = ambiente
    main(["quarentena", "mover", str(area / "Docs" / "b.txt"), "--sim", "--indice", str(banco)])
    na_quarentena = list((area / "_quarentena").rglob("b.txt"))[0]

    _respostas(monkeypatch, "s", "esvaziar")  # 2ª confirmação errada (minúsculas)
    main(["quarentena", "esvaziar", "--indice", str(banco)])
    assert "Cancelado" in capsys.readouterr().out
    assert na_quarentena.exists()

    _respostas(monkeypatch, "n")
    main(["quarentena", "esvaziar", "--indice", str(banco)])
    assert na_quarentena.exists()

    _respostas(monkeypatch, "s", "ESVAZIAR")
    assert main(["quarentena", "esvaziar", "--indice", str(banco)]) == 0
    saida = capsys.readouterr().out
    assert "NÃO DÁ PARA DESFAZER" in saida and "Liberado:" in saida
    assert not na_quarentena.exists()


def test_esvaziar_nao_aceita_sim(ambiente):
    _, banco = ambiente
    with pytest.raises(SystemExit):
        main(["quarentena", "esvaziar", "--sim", "--indice", str(banco)])


def test_desfazer_conflito_pergunta(ambiente, monkeypatch):
    area, banco = ambiente
    alvo = area / "Docs" / "b.txt"
    main(["quarentena", "mover", str(alvo), "--sim", "--indice", str(banco)])
    alvo.write_text("outro", encoding="utf-8")
    _respostas(monkeypatch, "r", "s")  # renomear, depois confirmar
    main(["quarentena", "desfazer", "--lote", "1", "--indice", str(banco)])
    assert alvo.read_text(encoding="utf-8") == "outro"
    assert (area / "Docs" / "b (restaurado).txt").exists()


def test_ha_quanto_tempo():
    hoje = date(2026, 10, 26)
    assert ha_quanto_tempo("2026-10-26T09:00:00", hoje) == "hoje"
    assert ha_quanto_tempo("2026-10-25T23:59:00", hoje) == "há 1 dia"
    assert ha_quanto_tempo("2026-09-26T10:00:00", hoje) == "há 30 dias"


def test_sem_teclado_conta_como_nao(ambiente, monkeypatch, capsys):
    area, banco = ambiente

    def sem_teclado(texto=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", sem_teclado)
    main(["quarentena", "mover", str(area / "Docs" / "b.txt"), "--indice", str(banco)])
    assert (area / "Docs" / "b.txt").exists()
