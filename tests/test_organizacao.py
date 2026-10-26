import itertools
from pathlib import Path

import pytest

from faxineiro.descricoes import descrever
from faxineiro.organizacao import (
    pasta_por_regras,
    pastas_esvaziadas,
    planejar_organizacao,
    sanear_pasta,
    sugerir_pastas,
)
from faxineiro.quarentena import DEPOIS_DE_MEXER, Quarentena
from faxineiro.scanner import escanear

from .conftest import bytes_pdf, bytes_png
from .falsos import ClienteFalso


class Travou(Exception):
    pass


def _pasta_por_nome(prompt: str) -> str:
    if "boleto" in prompt:
        return "Finanças"
    if "praia" in prompt:
        return "Viagens"
    return "Faculdade"


@pytest.fixture
def area(tmp_path):
    raiz = tmp_path / "pasta_teste"
    (raiz / "Downloads").mkdir(parents=True)
    (raiz / "Downloads" / "boleto_luz.pdf").write_bytes(bytes_pdf())
    (raiz / "Downloads" / "praia.png").write_bytes(bytes_png())
    (raiz / "Downloads" / "resumo.txt").write_text("resumo da aula", encoding="utf-8")
    return raiz


@pytest.fixture
def pronta(area, indice):
    escanear(area, indice)
    descrever(indice, area, ClienteFalso(), dormir=lambda s: None)
    return area


def _q(indice, area, **kw):
    return Quarentena(indice, limite=area, local=lambda arq: area / "_quarentena", **kw)


@pytest.mark.parametrize("entrada, esperado", [
    ("Documentos/Faculdade", "Documentos/Faculdade"),
    ("Documentos\\Faculdade\\2026\\Extra", "Documentos/Faculdade"),
    ("../../Windows/System32", "Windows/System32"),
    ("C:\\Users\\x", "Users/x"),
    ("Fotos: <viagem>?", "Fotos viagem"),
    ("CON/Notas", "Notas"),
    ("   ", None),
    (None, None),
    ("../..", None),
])
def test_sanear_pasta(entrada, esperado):
    assert sanear_pasta(entrada) == esperado


def test_sugestao_da_ia(pronta, indice):
    ia = ClienteFalso(pasta=_pasta_por_nome)
    r = sugerir_pastas(indice, pronta, ia)
    assert r.por_ia == 3 and r.por_regras == 0
    assert indice.buscar(str(pronta / "Downloads" / "boleto_luz.pdf"))["pasta_sugerida"] == "Documentos/Finanças"
    assert indice.buscar(str(pronta / "Downloads" / "praia.png"))["pasta_sugerida"] == "Imagens/Viagens"
    assert indice.buscar(str(pronta / "Downloads" / "resumo.txt"))["pasta_sugerida"] == "Textos/Faculdade"
    assert all(c["formato_json"] for c in ia.chamadas)
    # A pasta principal vem das regras; a IA só escolhe o assunto.
    assert "vai para a pasta 'Textos'" in ia.prompts[-1]


def test_ia_nao_consegue_mandar_documento_para_imagens(pronta, indice):
    """O 0.5b mandou contrato e currículo para 'Imagens/Viagens' na demo real: agora não dá mais."""
    sugerir_pastas(indice, pronta, ClienteFalso(pasta=lambda p: "Imagens/Viagens"))
    linha = indice.buscar(str(pronta / "Downloads" / "boleto_luz.pdf"))
    assert linha["pasta_sugerida"] == "Documentos/Viagens"  # o 1º nível é sempre o tipo real


def test_assuntos_iguais_viram_a_mesma_pasta(pronta, indice):
    respostas = iter(["finanças", "FINANÇAS", "Finanças"])
    (pronta / "Downloads" / "boleto_agua.pdf").write_bytes((pronta / "Downloads" / "boleto_luz.pdf").read_bytes() + b"%2")
    (pronta / "Downloads" / "boleto_gas.pdf").write_bytes((pronta / "Downloads" / "boleto_luz.pdf").read_bytes() + b"%3")
    escanear(pronta, indice)
    sugerir_pastas(indice, pronta, ClienteFalso(pasta=lambda p: next(respostas) if "boleto" in p else "Viagens"))
    pastas = {indice.buscar(str(pronta / "Downloads" / n))["pasta_sugerida"]
              for n in ("boleto_agua.pdf", "boleto_gas.pdf", "boleto_luz.pdf")}
    assert pastas == {"Documentos/Finanças"}


def test_assunto_inutil_cai_nas_regras(pronta, indice):
    r = sugerir_pastas(indice, pronta, ClienteFalso(pasta=lambda p: "Documentos"))
    assert r.por_regras == 3
    linha = indice.buscar(str(pronta / "Downloads" / "resumo.txt"))
    assert linha["pasta_sugerida"] == pasta_por_regras(linha)


@pytest.mark.parametrize("entrada, esperado", [
    ("finanças", "Finanças"), ("Documentos/Faculdade", "Faculdade"), ("Geral", None),
    ("Imagens", None), ("", None), ("ab", None), ("..\\..\\Windows", "Windows"),
    ("Imagens - Viagens", "Viagens"), ("Reunião de TCC - Novo Documento", "Reunião de TCC"),
    ("Anotações de Aula sobre Redes de Computadores", "Anotações de Aula"), ("2026", None),
    ("Dados de uma planilha", "Dados"), ("Arquivos de texto", None), ("Novo Arquivo", None),
])
def test_sanear_assunto(entrada, esperado):
    from faxineiro.organizacao import sanear_assunto

    assert sanear_assunto(entrada) == esperado


def test_resposta_perigosa_da_ia_e_saneada(pronta, indice):
    ia = ClienteFalso(pasta=lambda p: "..\\..\\..\\Windows")
    sugerir_pastas(indice, pronta, ia)
    assert indice.buscar(str(pronta / "Downloads" / "resumo.txt"))["pasta_sugerida"] == "Textos/Windows"


def test_ia_desligada_usa_regras(pronta, indice):
    r = sugerir_pastas(indice, pronta, ClienteFalso(ligado=False))
    assert r.por_regras == 3 and r.avisos
    linha = indice.buscar(str(pronta / "Downloads" / "praia.png"))
    assert linha["pasta_sugerida"] == pasta_por_regras(linha)
    assert linha["pasta_sugerida"].startswith("Imagens/")


def test_previa_nao_move(pronta, indice):
    sugerir_pastas(indice, pronta, ClienteFalso(pasta=_pasta_por_nome))
    plano = planejar_organizacao(indice, pronta, _q(indice, pronta))
    assert len(plano.validos) == 3
    assert (pronta / "Downloads" / "boleto_luz.pdf").exists()
    assert not (pronta / "Documentos").exists()


def test_aplicar_e_desfazer(pronta, indice):
    sugerir_pastas(indice, pronta, ClienteFalso(pasta=_pasta_por_nome))
    q = _q(indice, pronta)
    descricao_antes = indice.buscar(str(pronta / "Downloads" / "boleto_luz.pdf"))["descricao"]
    r = q.executar(planejar_organizacao(indice, pronta, q))
    assert len(r.feitos) == 3 and not r.falhas
    novo = pronta / "Documentos" / "Finanças" / "boleto_luz.pdf"
    assert novo.exists() and not (pronta / "Downloads" / "boleto_luz.pdf").exists()
    # índice: mesmo registro, caminho novo, descrição preservada (não precisa descrever de novo)
    linha = indice.buscar(str(novo))
    assert linha is not None and linha["descricao"] == descricao_antes
    assert indice.buscar(str(pronta / "Downloads" / "boleto_luz.pdf")) is None

    r2 = q.executar(q.planejar_desfazer(lote=r.lote_id))
    assert len(r2.feitos) == 3 and not r2.falhas
    assert (pronta / "Downloads" / "boleto_luz.pdf").exists()
    assert indice.buscar(str(pronta / "Downloads" / "boleto_luz.pdf"))["descricao"] == descricao_antes
    assert not (pronta / "Documentos").exists()  # pastas criadas pelo organizar foram removidas


def test_desfazer_remove_pasta_criada_que_varios_arquivos_dividem(pronta, indice):
    """Bug achado na demo real: 'Textos' era criada pelo 1º arquivo e sobrava vazia no desfazer."""
    assuntos = itertools.cycle(["Faculdade", "Trabalho", "Casa", "Receitas"])
    for nome in ("a_notas.txt", "b_notas.txt", "c_notas.txt"):
        (pronta / "Downloads" / nome).write_text(nome, encoding="utf-8")
    escanear(pronta, indice)
    sugerir_pastas(indice, pronta, ClienteFalso(pasta=lambda p: next(assuntos)))
    q = _q(indice, pronta)
    r = q.executar(planejar_organizacao(indice, pronta, q))
    assert (pronta / "Textos").is_dir()
    q.executar(q.planejar_desfazer(lote=r.lote_id))
    assert not (pronta / "Textos").exists()
    assert not (pronta / "Documentos").exists() and not (pronta / "Imagens").exists()


def _organizar_tudo(indice, pronta):
    sugerir_pastas(indice, pronta, ClienteFalso(pasta=_pasta_por_nome))
    q = _q(indice, pronta)
    r = q.executar(planejar_organizacao(indice, pronta, q))
    return q, r


def test_oferece_remover_so_as_pastas_que_o_organizar_esvaziou(pronta, indice):
    (pronta / "Antiga_vazia").mkdir()  # já estava vazia: nunca entra
    (pronta / "Fotos" / "viagem").mkdir(parents=True)
    (pronta / "Fotos" / "viagem" / "praia2.png").write_bytes(bytes_png() + b"2")
    escanear(pronta, indice)
    q, r = _organizar_tudo(indice, pronta)
    vazias = pastas_esvaziadas([p.origem for p in r.feitos], pronta)
    nomes = [p.relative_to(pronta).as_posix() for p in vazias]
    assert nomes == ["Fotos/viagem", "Downloads", "Fotos"]  # da mais funda para a mais rasa
    assert "Antiga_vazia" not in nomes
    # "Fotos" só tem a subpasta "viagem", que sai antes: entra no plano (bug da demo real)
    plano = q.planejar_remover_pastas(vazias)
    assert sorted(p.origem.name for p in plano.validos) == ["Downloads", "Fotos", "viagem"]
    q.executar(plano, lote_id=r.lote_id)
    assert not (pronta / "Fotos").exists() and (pronta / "Antiga_vazia").is_dir()


def test_pasta_com_outra_coisa_nao_entra(pronta, indice):
    (pronta / "Downloads" / "Sub_ja_vazia").mkdir()  # Downloads tinha uma subpasta vazia de antes
    escanear(pronta, indice)
    q, r = _organizar_tudo(indice, pronta)
    assert pastas_esvaziadas([p.origem for p in r.feitos], pronta) == []


def test_remover_pastas_esvaziadas_e_desfazer_recria(pronta, indice):
    q, r = _organizar_tudo(indice, pronta)
    plano = q.planejar_remover_pastas(pastas_esvaziadas([p.origem for p in r.feitos], pronta))
    assert [p.origem.name for p in plano.validos] == ["Downloads"]
    assert (pronta / "Downloads").is_dir()  # prévia não remove
    q.executar(plano, lote_id=r.lote_id)  # mesmo lote do organizar
    assert not (pronta / "Downloads").exists()

    r2 = q.executar(q.planejar_desfazer(lote=r.lote_id))  # um desfazer só
    assert not r2.falhas
    assert (pronta / "Downloads" / "boleto_luz.pdf").exists()
    assert not (pronta / "Documentos").exists()  # pastas criadas pelo organizar somem
    assert indice.itens_desfaziveis(lote=r.lote_id) == []


def test_remover_pasta_recusa_se_nao_estiver_vazia(pronta, indice):
    q = _q(indice, pronta)
    plano = q.planejar_remover_pastas([pronta / "Downloads"])
    assert plano.validos == [] and plano.passos[0].problema == "não está vazia"
    vazia = pronta / "Vazia"
    vazia.mkdir()
    plano = q.planejar_remover_pastas([vazia])
    (vazia / "chegou_depois.txt").write_text("x", encoding="utf-8")  # alguém pôs um arquivo depois da prévia
    r = q.executar(plano)
    assert r.feitos == [] and "não está mais vazia" in r.falhas[0][1]
    assert (vazia / "chegou_depois.txt").exists()


def test_travamento_ao_remover_pasta(pronta, indice):
    vazia = pronta / "Vazia"
    vazia.mkdir()

    def gancho(momento, passo):
        if momento == DEPOIS_DE_MEXER:
            raise Travou()

    qt = _q(indice, pronta, gancho=gancho)
    with pytest.raises(Travou):
        qt.executar(qt.planejar_remover_pastas([vazia]))
    mensagens = _q(indice, pronta).recuperar_diario()
    assert "Concluída (remover_pasta)" in mensagens[0]
    assert len(indice.itens_desfaziveis()) == 1


def test_desfazer_nao_remove_pasta_que_ja_existia(pronta, indice):
    (pronta / "Documentos" / "Finanças").mkdir(parents=True)
    (pronta / "Documentos" / "planilha_antiga.txt").write_text("minha", encoding="utf-8")
    sugerir_pastas(indice, pronta, ClienteFalso(pasta=_pasta_por_nome))
    q = _q(indice, pronta)
    r = q.executar(planejar_organizacao(indice, pronta, q))
    q.executar(q.planejar_desfazer(lote=r.lote_id))
    assert (pronta / "Documentos" / "Finanças").is_dir()  # existia antes: fica


def test_conflito_de_nome_nunca_sobrescreve(pronta, indice):
    destino = pronta / "Documentos" / "Finanças"
    destino.mkdir(parents=True)
    (destino / "boleto_luz.pdf").write_bytes(b"outro boleto")
    sugerir_pastas(indice, pronta, ClienteFalso(pasta=_pasta_por_nome))
    q = _q(indice, pronta)
    plano = planejar_organizacao(indice, pronta, q)
    passo = next(p for p in plano.validos if p.origem.name == "boleto_luz.pdf")
    assert passo.renomeado and passo.destino.name == "boleto_luz (2).pdf"
    q.executar(plano)
    assert (destino / "boleto_luz.pdf").read_bytes() == b"outro boleto"
    assert (destino / "boleto_luz (2).pdf").exists()


def test_ja_na_pasta_sugerida_fica_de_fora(pronta, indice):
    for linha in indice.todos(str(pronta) + "\\"):
        indice.gravar_pasta_sugerida(linha["id"], "Downloads")
    assert planejar_organizacao(indice, pronta, _q(indice, pronta)).passos == []


def test_travamento_no_meio_do_organizar(pronta, indice):
    sugerir_pastas(indice, pronta, ClienteFalso(pasta=_pasta_por_nome))

    def gancho(momento, passo):
        if momento == DEPOIS_DE_MEXER:
            raise Travou()

    qt = _q(indice, pronta, gancho=gancho)
    with pytest.raises(Travou):
        qt.executar(planejar_organizacao(indice, pronta, qt))
    q = _q(indice, pronta)
    mensagens = q.recuperar_diario()
    assert mensagens and "Concluída (organizar)" in mensagens[0]
    movido = Path(indice.itens_desfaziveis()[0]["destino"])
    assert movido.exists() and indice.buscar(str(movido)) is not None


def test_organizar_recusa_fora_da_area(pronta, indice, tmp_path):
    q = _q(indice, pronta)
    plano = q.planejar_organizar([(pronta / "Downloads" / "resumo.txt", tmp_path / "fora" / "resumo.txt")])
    assert plano.validos == [] and "fora da área" in plano.passos[0].problema
