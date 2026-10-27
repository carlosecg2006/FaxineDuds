"""Fase 7A: ler o PC real é permitido; mudar o disco continua travado na pasta_teste."""

from pathlib import Path

import pytest
from PIL import Image

from faxineiro import config
from faxineiro.config import Bloqueios, bloqueios_do_pc, dentro_da_pasta_teste, pode_ler
from faxineiro.conversor import ConversaoRecusada, Ferramentas, planejar_conversao
from faxineiro.espaco import arquivos_de_sistema, calcular
from faxineiro.indice import Registro
from faxineiro.quarentena import Quarentena

GB = 1024 ** 3
AREAS = (Path(r"C:\Users\Carlos Eduardo"), Path("D:\\"))


# --- regra 5 dividida ------------------------------------------------------------------


@pytest.mark.parametrize("pasta, pode", [
    (r"C:\Users\Carlos Eduardo", True),
    (r"C:\Users\Carlos Eduardo\Documents\faculdade", True),
    (r"D:\\", True),
    (r"D:\Jogos\saves", True),
    (r"C:\Users\Outra Pessoa", False),
    (r"C:\Windows\System32", False),
    (r"C:\Users\Carlos Eduardo\AppData\Local", False),  # dentro de pasta bloqueada: nunca
    (r"D:\Windows", False),  # pasta de sistema na raiz do D:
    (r"D:\Program Files\Steam", False),
])
def test_pode_ler(pasta, pode):
    assert pode_ler(pasta, AREAS) is pode


def test_pasta_teste_sempre_pode_ler():
    assert pode_ler(config.PASTA_TESTE, ())


def test_mudar_o_disco_continua_so_na_pasta_teste():
    assert not dentro_da_pasta_teste(r"C:\Users\Carlos Eduardo\Documents")
    assert not dentro_da_pasta_teste(r"D:\Jogos")


def test_quarentena_recusa_o_pc_real(indice, tmp_path):
    """Mesmo podendo LER o PC, o executor da Fase 3 continua recusando mover fora da pasta_teste."""
    q = Quarentena(indice)  # limite padrão = pasta_teste
    alvo = tmp_path / "arquivo_do_pc.txt"
    alvo.write_text("meu", encoding="utf-8")
    plano = q.planejar_mover([alvo])
    assert plano.validos == [] and "fora da área" in plano.passos[0].problema
    assert q.planejar_organizar([(alvo, tmp_path / "x" / "arquivo_do_pc.txt")]).validos == []
    assert alvo.exists()


def test_converter_recusa_o_pc_real(tmp_path):
    Image.new("RGB", (4, 4)).save(tmp_path / "foto.png")
    with pytest.raises(ConversaoRecusada, match="fora da área"):
        planejar_conversao(tmp_path / "foto.png", "jpg", ferramentas=Ferramentas(None, None))


# --- bloqueios em qualquer unidade ----------------------------------------------------------


@pytest.mark.parametrize("pasta", [r"D:\Windows", r"D:\Program Files", r"E:\Recovery", r"D:\$WINDOWS.~TMP",
                                   r"D:\WUDownloadCache", r"D:\Jogos\WUDownloadCache", r"C:\Windows.old"])
def test_pastas_de_sistema_em_qualquer_unidade(pasta):
    assert Bloqueios().bloqueada(pasta)


@pytest.mark.parametrize("pasta", [r"D:\Jogos\Windows", r"D:\Backup\Program Files", r"D:\Programas"])
def test_nome_parecido_fora_da_raiz_nao_bloqueia(pasta):
    assert not Bloqueios().bloqueada(pasta)  # "Windows" só é sistema na raiz da unidade


def test_pasta_do_app_fica_fora_da_varredura_do_pc():
    b = bloqueios_do_pc()
    assert b.bloqueada(config.RAIZ_PROJETO)
    assert b.bloqueada(config.RAIZ_PROJETO / "pasta_teste")
    assert not Bloqueios().bloqueada(config.PASTA_TESTE)  # a varredura da própria pasta_teste continua


# --- espaço explicado × não explicado --------------------------------------------------------


def _gravar(indice, caminho, tamanho):
    indice.gravar(Registro(caminho=caminho, pasta_raiz=str(Path(caminho).parent), nome=Path(caminho).name,
                           extensao="bin", tamanho=tamanho, criado_em="2026-01-01T00:00:00",
                           modificado_em="2026-01-01T00:00:00", modificado_ns=1, tipo_real="desconhecido",
                           categoria="outro", extensao_confere=True), 1, "agora")


def test_conta_do_espaco_fecha(indice):
    _gravar(indice, r"C:\Users\Carlos Eduardo\Videos\filme.mkv", 30 * GB)
    _gravar(indice, r"C:\Users\Carlos Eduardo\foto.jpg", 2 * GB)
    _gravar(indice, r"D:\Jogos\jogo.iso", 50 * GB)  # outra unidade: não conta no C:
    indice.confirmar()
    e = calcular(indice, "C:\\", uso=lambda r: (118 * GB, 113 * GB, 5 * GB),
                 sistema=lambda r: {"pagefile.sys": 4 * GB, "swapfile.sys": GB // 4})
    assert e.explicado == 32 * GB
    assert e.sistema_total == 4 * GB + GB // 4
    assert e.nao_explicado == 113 * GB - 32 * GB - 4 * GB - GB // 4
    assert e.explicado + e.sistema_total + e.nao_explicado == e.usado


def test_conta_do_espaco_com_backup_do_windows(indice):
    e = calcular(indice, "D:\\", uso=lambda r: (530 * GB, 112 * GB, 418 * GB), sistema=lambda r: {},
                 backups=lambda r: {"Backup do Windows (gerencie pelo Histórico de Arquivos)": 20 * GB})
    assert e.backups_total == 20 * GB
    assert e.explicado + e.sistema_total + e.backups_total + e.nao_explicado == e.usado


def test_backup_do_windows_so_com_o_total(tmp_path):
    from faxineiro.espaco import backups_do_windows

    (tmp_path / "FileHistory" / "carlo" / "Data").mkdir(parents=True)
    (tmp_path / "FileHistory" / "carlo" / "Data" / "a (2021_12_07).md").write_bytes(b"x" * 300)
    (tmp_path / "FileHistory" / "b.txt").write_bytes(b"x" * 200)
    (tmp_path / "Outra").mkdir()
    (tmp_path / "Outra" / "c.txt").write_bytes(b"x" * 999)
    assert backups_do_windows(tmp_path) == {"Backup do Windows (gerencie pelo Histórico de Arquivos)": 500}


# --- FileHistory: nunca no índice, no Raio-X ou em ações ------------------------------------


@pytest.mark.parametrize("pasta", [r"D:\FileHistory", r"E:\FileHistory", r"D:\Backups\FileHistory"])
def test_filehistory_bloqueado_em_qualquer_unidade(pasta):
    assert Bloqueios().bloqueada(pasta)


@pytest.fixture
def com_backup(tmp_path):
    raiz = tmp_path / "disco"
    (raiz / "FileHistory" / "carlo").mkdir(parents=True)
    (raiz / "FileHistory" / "carlo" / "foto (2021_12_07).jpg").write_bytes(b"versao antiga" * 50)
    (raiz / "Fotos").mkdir()
    (raiz / "Fotos" / "foto.jpg").write_bytes(b"versao antiga" * 50)  # "igual" ao backup
    return raiz


def test_varredura_pula_o_filehistory(com_backup, indice):
    from faxineiro.scanner import escanear

    p = escanear(com_backup, indice)
    assert p.novos == 1
    assert indice.buscar(str(com_backup / "Fotos" / "foto.jpg")) is not None
    assert all("FileHistory" not in l["caminho"] for l in indice.todos(str(com_backup) + "\\"))


def test_linhas_antigas_do_filehistory_saem_do_indice(com_backup, indice):
    """Arquivos indexados antes da regra nova saem do índice (só a linha; o arquivo fica)."""
    from faxineiro.scanner import escanear

    antigo = com_backup / "FileHistory" / "carlo" / "foto (2021_12_07).jpg"
    _gravar(indice, str(antigo), antigo.stat().st_size)
    indice.con.execute("UPDATE arquivos SET pasta_raiz = ?", (str(com_backup),))
    indice.confirmar()
    p = escanear(com_backup, indice)
    assert p.fora_por_bloqueio == 1
    assert indice.buscar(str(antigo)) is None
    assert antigo.exists()  # o arquivo do usuário nunca é tocado


def test_raiox_nunca_mostra_o_filehistory(com_backup, indice):
    from faxineiro import raiox
    from faxineiro.scanner import escanear

    escanear(com_backup, indice)
    assert raiox.encontrar_duplicados(indice, com_backup).grupos == []  # o backup não vira "duplicado"


def test_acoes_recusam_o_filehistory(com_backup, indice):
    q = Quarentena(indice, limite=com_backup, local=lambda a: com_backup / "_quarentena")
    dentro = com_backup / "FileHistory" / "carlo" / "foto (2021_12_07).jpg"
    assert "pasta bloqueada" in q.planejar_mover([dentro]).passos[0].problema
    assert "pasta bloqueada" in q.planejar_organizar([(dentro, com_backup / "Fotos" / "x.jpg")]).passos[0].problema
    assert "pasta bloqueada" in q.planejar_organizar(
        [(com_backup / "Fotos" / "foto.jpg", com_backup / "FileHistory" / "x.jpg")]).passos[0].problema
    with pytest.raises(ConversaoRecusada, match="pasta bloqueada"):
        planejar_conversao(dentro, "png", limite=com_backup, ferramentas=Ferramentas(None, None))


# --- OneDrive "só na nuvem": nunca abrir (abrir = baixar o arquivo inteiro) --------------------


@pytest.fixture
def nuvem(tmp_path, monkeypatch):
    """Finge que os arquivos com 'nuvem' no nome estão só na nuvem (atributo do Windows)."""
    from faxineiro import scanner

    raiz = tmp_path / "OneDrive"
    raiz.mkdir()
    (raiz / "foto_nuvem.jpg").write_bytes(b"\xff\xd8\xff" + bytes(5000))
    (raiz / "copia_nuvem.jpg").write_bytes(b"\xff\xd8\xff" + bytes(5000))  # "igual"
    (raiz / "relatorio_nuvem.txt").write_text("conteudo", encoding="utf-8")
    (raiz / "local.txt").write_text("conteudo local", encoding="utf-8")
    def falso(st):
        return "nuvem" in Path(falso.atual).name  # só o nome: a pasta do pytest também diz "nuvem"

    abertos = []

    def detector(caminho):
        abertos.append(Path(caminho).name)
        from faxineiro.tipos import detectar_tipo

        return detectar_tipo(caminho)

    def montar(caminho, st, pasta_raiz, aparelho, det, _m=scanner._montar_registro):
        falso.atual = caminho
        return _m(caminho, st, pasta_raiz, aparelho, det)

    monkeypatch.setattr(scanner, "so_na_nuvem", falso)
    monkeypatch.setattr(scanner, "_montar_registro", montar)
    return raiz, detector, abertos


def test_so_na_nuvem_nao_e_aberto(nuvem, indice):
    from faxineiro.scanner import escanear

    raiz, detector, abertos = nuvem
    escanear(raiz, indice, detector=detector)
    assert abertos == ["local.txt"]  # só o arquivo local foi aberto
    l = indice.buscar(str(raiz / "foto_nuvem.jpg"))
    assert l["aparelho"] == "nuvem" and l["conectado"] == 0
    assert (l["tipo_real"], l["categoria"]) == ("jpg", "imagem")  # palpite pela extensão


def test_so_na_nuvem_fica_fora_do_raiox_e_do_espaco(nuvem, indice):
    from faxineiro import raiox
    from faxineiro.hashes import Hasher
    from faxineiro.scanner import escanear

    raiz, detector, _ = nuvem
    escanear(raiz, indice, detector=detector)
    hasher = Hasher()
    assert raiox.encontrar_duplicados(indice, raiz, hasher=hasher).grupos == []
    assert hasher.parciais == 0  # nenhum arquivo da nuvem foi lido para calcular hash
    assert raiox.pesados(indice, raiz, minimo=0) and all(
        l["aparelho"] != "nuvem" for l in raiox.pesados(indice, raiz, minimo=0))
    assert indice.soma_por_prefixo(str(raiz)) == (raiz / "local.txt").stat().st_size


def test_so_na_nuvem_nao_vai_para_a_ia(nuvem, indice):
    from faxineiro.descricoes import descrever, descrever_arquivo
    from faxineiro.scanner import escanear

    from .falsos import ClienteFalso

    raiz, detector, _ = nuvem
    escanear(raiz, indice, detector=detector)
    ia = ClienteFalso()
    descrever(indice, raiz, ia, dormir=lambda s: None)
    assert not any("nuvem" in p for p in ia.prompts)
    p = descrever_arquivo(indice, raiz / "relatorio_nuvem.txt", ClienteFalso())
    assert any("só na nuvem" in a for a in p.avisos)


def test_atributo_de_nuvem_do_windows():
    from types import SimpleNamespace

    from faxineiro.scanner import so_na_nuvem

    assert so_na_nuvem(SimpleNamespace(st_file_attributes=0x00400000))  # RECALL_ON_DATA_ACCESS
    assert so_na_nuvem(SimpleNamespace(st_file_attributes=0x00001000 | 0x20))  # OFFLINE
    assert not so_na_nuvem(SimpleNamespace(st_file_attributes=0x20))  # arquivo normal
    assert not so_na_nuvem(SimpleNamespace())  # fora do Windows


def test_arquivos_de_sistema_pela_listagem(tmp_path):
    (tmp_path / "pagefile.sys").write_bytes(b"x" * 100)
    (tmp_path / "hiberfil.sys").write_bytes(b"x" * 50)
    (tmp_path / "outro.sys").write_bytes(b"x")
    assert arquivos_de_sistema(tmp_path) == {"pagefile.sys": 100, "hiberfil.sys": 50}


def test_cli_recusa_ler_appdata(tmp_path, capsys):
    from faxineiro.__main__ import main

    assert main(["escanear", str(tmp_path), "--indice", str(tmp_path / "i.sqlite")]) == 2
    assert "Recusado" in capsys.readouterr().err


# --- pastas de programa (.minecraft, .vscode...): o Raio-X não lista o que tem dentro ---------


@pytest.fixture
def com_programas(tmp_path, indice):
    from faxineiro.scanner import escanear

    casa = tmp_path / "casa"
    jogo = casa / ".minecraft" / "versions"
    jogo.mkdir(parents=True)
    (jogo / "1.21.jar").write_bytes(b"J" * 3000)
    (jogo / "forge.jar").write_bytes(b"J" * 3000)  # duplicado "normal" do jogo
    (jogo / "grande.jar").write_bytes(b"G" * 50_000)
    (jogo / "~$lixo.tmp").write_bytes(b"x")
    (jogo / "vazio.dat").write_bytes(b"")
    (casa / ".minecraft" / "logs").mkdir()  # pasta vazia do jogo
    (casa / "Curseforge" / "x").mkdir(parents=True)  # nome com maiúscula também conta
    (casa / "Curseforge" / "x" / "mod.jar").write_bytes(b"M" * 20_000)
    docs = casa / "Documentos"
    docs.mkdir()
    (docs / "a.txt").write_text("igual" * 300, encoding="utf-8")
    (docs / "b.txt").write_text("igual" * 300, encoding="utf-8")
    (docs / "~$rascunho.docx").write_bytes(b"x")
    (casa / "Vazia").mkdir()
    escanear(casa, indice)
    return casa


def test_raiox_nao_lista_dentro_de_pasta_de_programa(com_programas, indice):
    from faxineiro import raiox

    casa = com_programas
    grupos = raiox.encontrar_duplicados(indice, casa).grupos
    assert [sorted(Path(a["caminho"]).name for a in g.arquivos) for g in grupos] == [["a.txt", "b.txt"]]
    assert raiox.pesados(indice, casa, minimo=0) and all(
        ".minecraft" not in l["caminho"] and "Curseforge" not in l["caminho"]
        for l in raiox.pesados(indice, casa, minimo=0))
    lx = raiox.lixo(indice, casa)
    assert [l["nome"] for l in lx.temporarios] == ["~$rascunho.docx"]
    assert lx.vazios == []
    assert raiox.pastas_vazias(casa) == [str(casa / "Vazia")]
    assert all(".minecraft" not in l["caminho"] for l in raiox.extensao_errada(indice, casa))


def test_raiox_da_propria_pasta_de_programa_olha_dentro(com_programas, indice):
    from faxineiro import raiox

    jogo = com_programas / ".minecraft"
    grupos = raiox.encontrar_duplicados(indice, jogo).grupos
    assert [sorted(Path(a["caminho"]).name for a in g.arquivos) for g in grupos] == [["1.21.jar", "forge.jar"]]


def test_espaco_mostra_o_total_de_cada_pasta_de_programa(com_programas, indice):
    casa = com_programas
    e = calcular(indice, str(casa), uso=lambda r: (100 * GB, 50 * GB, 50 * GB),
                 sistema=lambda r: {}, backups=lambda r: {})
    jogo = 3000 + 3000 + 50_000 + 1
    assert list(e.programas.items()) == [(str(casa / ".minecraft"), jogo), (str(casa / "Curseforge"), 20_000)]
    # Continuam contando no "explicado": nada some da conta do disco.
    assert e.explicado == indice.soma_por_prefixo(str(Path(str(casa)).anchor))


def test_pasta_de_programa_dentro_de_outra_conta_so_na_de_fora(tmp_path, indice):
    from faxineiro.scanner import escanear

    dentro = tmp_path / "casa" / ".minecraft" / "mods" / ".vscode"
    dentro.mkdir(parents=True)
    (dentro / "s.json").write_bytes(b"1" * 10)
    (tmp_path / "casa" / ".minecraft" / "a.jar").write_bytes(b"2" * 5)
    escanear(tmp_path / "casa", indice)
    assert indice.pastas_de_programa(str(tmp_path), config.PASTAS_DE_PROGRAMA) == {
        str(tmp_path / "casa" / ".minecraft"): 15}


def test_pasta_de_programa_e_bloco_para_organizar(tmp_path):
    from faxineiro.protecoes import Protecoes

    p = Protecoes(nuvem_pastas=[])
    assert p.motivo_bloco(tmp_path / ".minecraft")
    assert p.motivo_bloco(tmp_path / "CurseForge")
    assert p.motivo_bloco(tmp_path / "Documentos") is None
