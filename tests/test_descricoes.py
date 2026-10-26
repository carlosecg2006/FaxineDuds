import os
import random

import pytest

from faxineiro.descricoes import ConfigDescricao, descrever, descrever_arquivo, descricao_por_regras, precisa_ia
from faxineiro.scanner import escanear

from .conftest import bytes_png, bytes_zip
from .falsos import MB, ClienteFalso

SEM_ESPERA = {"dormir": lambda s: None}
DESCONHECIDO = bytes([0, 1, 2, 3]) + random.Random(5).randbytes(2000)  # sempre os mesmos bytes
MUITA_MEMORIA = lambda: 3000 * MB  # noqa: E731
POUCA_MEMORIA = lambda: 300 * MB  # noqa: E731


@pytest.fixture
def area(tmp_path):
    raiz = tmp_path / "pasta_teste"
    (raiz / "Faculdade").mkdir(parents=True)
    (raiz / "Fotos").mkdir()
    (raiz / "Faculdade" / "resumo.txt").write_text(
        "Resumo de Engenharia de Software. " * 200 + "SEGREDO_DO_FIM", encoding="utf-8")
    (raiz / "Faculdade" / "tcc.docx").write_bytes(bytes_zip({
        "[Content_Types].xml": b'<Types><Override ContentType="application/vnd.openxmlformats-'
                               b'officedocument.wordprocessingml.document.main+xml"/></Types>',
        "word/document.xml": b"<w:t>Trabalho de Conclusao de Curso sobre redes</w:t>"}))
    (raiz / "Fotos" / "praia.png").write_bytes(bytes_png())
    (raiz / "filme.bin").write_bytes(DESCONHECIDO)  # tipo desconhecido
    (raiz / "musica.zip").write_bytes(bytes_zip({"a.txt": b"x"}))  # óbvio: compactado
    return raiz


@pytest.fixture
def escaneada(area, indice):
    escanear(area, indice)
    return area


def _linha(indice, caminho):
    return indice.buscar(str(caminho))


# --- regras primeiro: a IA só pega o que precisa -------------------------------------


def test_regras_resolvem_o_obvio_e_ia_so_o_revisar(escaneada, indice):
    ia = ClienteFalso()
    p = descrever(indice, escaneada, ia, **SEM_ESPERA)
    assert p.por_regras == 5  # todos ganham descrição por regras primeiro
    assert p.total == 3  # só resumo.txt, tcc.docx e filme.bin (desconhecido) vão para a IA
    perguntados = " ".join(ia.prompts)
    assert "praia.png" not in perguntados and "musica.zip" not in perguntados
    assert _linha(indice, escaneada / "Fotos" / "praia.png")["revisar"] == 0
    assert _linha(indice, escaneada / "Faculdade" / "resumo.txt")["descricao_origem"] == "ia"


def test_precisa_ia():
    assert precisa_ia({"tamanho": 10, "categoria": "texto", "tipo_real": "texto"})
    assert precisa_ia({"tamanho": 10, "categoria": "documento", "tipo_real": "pdf"})
    assert precisa_ia({"tamanho": 10, "categoria": "outro", "tipo_real": "desconhecido"})
    assert not precisa_ia({"tamanho": 10, "categoria": "imagem", "tipo_real": "png"})
    assert not precisa_ia({"tamanho": 0, "categoria": "texto", "tipo_real": "vazio"})


def test_so_regras_nao_chama_a_ia(escaneada, indice):
    ia = ClienteFalso()
    p = descrever(indice, escaneada, ia, so_regras=True, **SEM_ESPERA)
    assert ia.chamadas == [] and p.revisar == 3


def test_prompt_tem_nome_pasta_e_so_o_comeco(escaneada, indice):
    ia = ClienteFalso()
    descrever(indice, escaneada, ia, **SEM_ESPERA)
    prompt = next(p for p in ia.prompts if "resumo.txt" in p)
    assert "Nome: resumo.txt" in prompt and "Pasta: Faculdade" in prompt
    assert "Resumo de Engenharia de Software" in prompt
    assert "SEGREDO_DO_FIM" not in prompt  # o arquivo nunca vai inteiro
    assert len(prompt) < 2500
    assert "Trabalho de Conclusao de Curso" in next(p for p in ia.prompts if "tcc.docx" in p)


def test_desconhecido_vai_so_com_metadados(escaneada, indice):
    ia = ClienteFalso()
    descrever(indice, escaneada, ia, **SEM_ESPERA)
    prompt = next(p for p in ia.prompts if "filme.bin" in p)
    assert "Começo do conteúdo" not in prompt and "Tamanho:" in prompt


# --- memória ------------------------------------------------------------------------


def test_pouca_memoria_usa_so_regras_e_avisa(escaneada, indice):
    ia = ClienteFalso(ja_carregado=False, tamanho_modelo=400 * MB)
    p = descrever(indice, escaneada, ia, memoria=POUCA_MEMORIA, **SEM_ESPERA)
    assert ia.chamadas == []
    assert p.revisar == 3 and not p.ia_ligada
    assert any("Pouca memória livre" in a and "300 MB" in a for a in p.avisos)


def test_memoria_suficiente_usa_a_ia(escaneada, indice):
    ia = ClienteFalso(ja_carregado=False)
    p = descrever(indice, escaneada, ia, memoria=MUITA_MEMORIA, **SEM_ESPERA)
    assert p.por_ia == 3


def test_memoria_cai_no_meio_para_a_ia(tmp_path, indice):
    raiz = tmp_path / "muitos"
    raiz.mkdir()
    for i in range(30):
        (raiz / f"nota_{i:02d}.txt").write_text(f"nota {i}", encoding="utf-8")
    escanear(raiz, indice)
    leituras = iter([3000 * MB] + [100 * MB] * 10)
    ia = ClienteFalso(ja_carregado=False, falhar=lambda p: True)  # falha => nunca "usou" a IA
    p = descrever(indice, raiz, ia, memoria=lambda: next(leituras),
                  cfg=ConfigDescricao(tamanho_lote=5, max_falhas_seguidas=99), **SEM_ESPERA)
    assert len(ia.chamadas) == 5  # 1º lote; depois a memória caiu e a IA parou
    assert any("Pouca memória" in a for a in p.avisos)


def test_descarrega_o_modelo_ao_terminar(escaneada, indice):
    ia = ClienteFalso()
    descrever(indice, escaneada, ia, **SEM_ESPERA)
    assert ia.descarregamentos == 1


def test_nao_descarrega_se_nem_usou(escaneada, indice):
    ia = ClienteFalso(ligado=False)
    descrever(indice, escaneada, ia, **SEM_ESPERA)
    assert ia.descarregamentos == 0


# --- falhas, pausa, retomada ------------------------------------------------------------


def test_ollama_desligado_fica_tudo_para_revisar(escaneada, indice):
    p = descrever(indice, escaneada, ClienteFalso(ligado=False), **SEM_ESPERA)
    assert p.por_ia == 0 and p.revisar == 3 and not p.ia_ligada
    assert any("desligado" in a for a in p.avisos)


def test_timeout_em_um_arquivo_so_ele_fica_para_revisar(escaneada, indice):
    ia = ClienteFalso(falhar=lambda prompt: "tcc.docx" in prompt)
    p = descrever(indice, escaneada, ia, **SEM_ESPERA)
    assert _linha(indice, escaneada / "Faculdade" / "tcc.docx")["revisar"] == 1
    assert _linha(indice, escaneada / "Faculdade" / "resumo.txt")["descricao_origem"] == "ia"
    assert any("demorou demais" in a for a in p.avisos)


def test_falhas_seguidas_desistem_da_ia(tmp_path, indice):
    raiz = tmp_path / "muitos"
    raiz.mkdir()
    for i in range(8):
        (raiz / f"nota_{i}.txt").write_text(f"nota {i}", encoding="utf-8")
    escanear(raiz, indice)
    ia = ClienteFalso(falhar=lambda prompt: True)
    p = descrever(indice, raiz, ia, cfg=ConfigDescricao(max_falhas_seguidas=3), **SEM_ESPERA)
    assert len(ia.chamadas) == 3  # depois da 3ª falha, nem tenta mais
    assert p.revisar == 8
    assert any("falhas seguidas" in a for a in p.avisos)


def test_aquecimento_usa_tempo_maior_so_na_primeira(escaneada, indice):
    ia = ClienteFalso()
    descrever(indice, escaneada, ia, cfg=ConfigDescricao(timeout=30, timeout_aquecimento=200), **SEM_ESPERA)
    tempos = [c["timeout"] for c in ia.chamadas]
    assert tempos[0] == 200 and set(tempos[1:]) == {30}


def test_segunda_rodada_nao_refaz(escaneada, indice):
    descrever(indice, escaneada, ClienteFalso(), **SEM_ESPERA)
    ia = ClienteFalso()
    p = descrever(indice, escaneada, ia, **SEM_ESPERA)
    assert p.por_regras == 0 and p.total == 0 and ia.chamadas == []


def test_arquivo_alterado_e_refeito(escaneada, indice):
    descrever(indice, escaneada, ClienteFalso(), **SEM_ESPERA)
    alvo = escaneada / "Faculdade" / "resumo.txt"
    alvo.write_text("conteúdo totalmente novo", encoding="utf-8")
    st = alvo.stat()
    os.utime(alvo, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    escanear(escaneada, indice)
    ia = ClienteFalso()
    p = descrever(indice, escaneada, ia, **SEM_ESPERA)
    assert p.por_regras == 1 and p.total == 1
    assert "conteúdo totalmente novo" in ia.prompts[0]


def test_pausar_e_continuar_de_onde_parou(tmp_path, indice):
    raiz = tmp_path / "lote"
    raiz.mkdir()
    for i in range(25):
        (raiz / f"arq_{i:02d}.txt").write_text(f"texto {i}", encoding="utf-8")
    escanear(raiz, indice)
    cfg = ConfigDescricao(tamanho_lote=10)
    lotes = []
    p1 = descrever(indice, raiz, ClienteFalso(), cfg=cfg, parar=lambda: len(lotes) >= 1,
                   ao_progredir=lambda p: lotes.append(p.feitos), **SEM_ESPERA)
    assert p1.pausado and p1.por_ia == 10  # parou depois do 1º lote gravado
    ia = ClienteFalso()
    p2 = descrever(indice, raiz, ia, cfg=cfg, **SEM_ESPERA)
    assert p2.total == 15 and p2.por_ia == 15 and not p2.pausado
    assert not any("arq_00" in pr for pr in ia.prompts)  # não refez os já descritos


def test_limite_por_rodada(escaneada, indice):
    p = descrever(indice, escaneada, ClienteFalso(), limite=2, **SEM_ESPERA)
    assert p.por_ia == 2
    assert descrever(indice, escaneada, ClienteFalso(), **SEM_ESPERA).por_ia == 1


# --- comando para um arquivo específico ----------------------------------------------


def test_descrever_um_arquivo_mesmo_obvio(escaneada, indice):
    descrever(indice, escaneada, ClienteFalso(), so_regras=True, **SEM_ESPERA)
    ia = ClienteFalso()
    p = descrever_arquivo(indice, escaneada / "musica.zip", ia)
    assert len(ia.chamadas) == 1 and p.por_ia == 1
    assert _linha(indice, escaneada / "musica.zip")["descricao_origem"] == "ia"
    assert ia.descarregamentos == 1


def test_descrever_um_arquivo_com_pouca_memoria(escaneada, indice):
    ia = ClienteFalso(ja_carregado=False)
    p = descrever_arquivo(indice, escaneada / "Faculdade" / "resumo.txt", ia, memoria=POUCA_MEMORIA)
    assert ia.chamadas == [] and p.por_regras == 1
    assert any("Pouca memória" in a for a in p.avisos)


def test_descrever_arquivo_fora_do_indice(tmp_path, indice):
    p = descrever_arquivo(indice, tmp_path / "nao_existe.txt", ClienteFalso())
    assert p.feitos == 0 and "não está no índice" in p.avisos[0]


def test_imagem_com_visao_pelo_comando_de_arquivo(escaneada, indice):
    ia = ClienteFalso(visao="llava:7b")
    descrever_arquivo(indice, escaneada / "Fotos" / "praia.png", ia)
    chamada = ia.chamadas[0]
    assert chamada["modelo"] == "llava:7b" and chamada["imagens"]
    assert _linha(indice, escaneada / "Fotos" / "praia.png")["descricao_origem"] == "ia_visao"


def test_descricao_por_regras_legivel(escaneada, indice):
    texto = descricao_por_regras(_linha(indice, escaneada / "Fotos" / "praia.png"))
    assert texto.startswith("Imagem PNG com o nome 'praia.png' em 'Fotos'")


def test_resposta_comprida_e_cortada():
    from faxineiro.descricoes import _limpar_resposta

    assert _limpar_resposta('Descrição: "Contrato de aluguel. Tem 3 páginas."') == "Contrato de aluguel."
    longa = "arquivo de aula, " + ", ".join(["rede"] * 40)
    assert len(_limpar_resposta(longa).split()) == 25 and _limpar_resposta(longa).endswith("…")


def test_sem_cliente_funciona(escaneada, indice):
    p = descrever(indice, escaneada, None, **SEM_ESPERA)
    assert p.por_regras == 5 and p.revisar == 3
