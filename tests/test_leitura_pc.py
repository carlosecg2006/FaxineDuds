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


def test_arquivos_de_sistema_pela_listagem(tmp_path):
    (tmp_path / "pagefile.sys").write_bytes(b"x" * 100)
    (tmp_path / "hiberfil.sys").write_bytes(b"x" * 50)
    (tmp_path / "outro.sys").write_bytes(b"x")
    assert arquivos_de_sistema(tmp_path) == {"pagefile.sys": 100, "hiberfil.sys": 50}


def test_cli_recusa_ler_appdata(tmp_path, capsys):
    from faxineiro.__main__ import main

    assert main(["escanear", str(tmp_path), "--indice", str(tmp_path / "i.sqlite")]) == 2
    assert "Recusado" in capsys.readouterr().err
