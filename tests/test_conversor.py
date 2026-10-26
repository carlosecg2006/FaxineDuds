"""Conversor (Fase 5B). Imagens sempre; áudio/vídeo com o ffmpeg real (pulados se ele faltar)."""

import subprocess
import time
from pathlib import Path

import pytest
from PIL import Image

from faxineiro import conversor
from faxineiro.conversor import (
    EXTRAIR_AUDIO,
    ConversaoRecusada,
    Ferramentas,
    converter,
    formatos_possiveis,
    ler_progresso,
    localizar_ffmpeg,
    planejar_conversao,
)
from faxineiro.quarentena import Quarentena
from faxineiro.scanner import escanear

FERRAMENTAS = localizar_ffmpeg()
precisa_ffmpeg = pytest.mark.skipif(not FERRAMENTAS.tem_ffmpeg, reason="ffmpeg não encontrado")
SEM_FFMPEG = Ferramentas(None, None)


@pytest.fixture
def area(tmp_path):
    raiz = tmp_path / "pasta_teste"
    raiz.mkdir()
    Image.new("RGBA", (64, 48), (255, 0, 0, 128)).save(raiz / "logo.png")
    Image.new("RGB", (80, 60), "blue").save(raiz / "foto.jpg")
    return raiz


def _gerar(destino: Path, *args: str) -> Path:
    subprocess.run([str(FERRAMENTAS.ffmpeg), "-hide_banner", "-loglevel", "error", "-y", *args, str(destino)],
                   check=True, timeout=120)
    return destino


@pytest.fixture
def midia(area):
    if not FERRAMENTAS.tem_ffmpeg:
        pytest.skip("ffmpeg não encontrado")
    video = _gerar(area / "video.mp4", "-f", "lavfi", "-i", "testsrc=duration=3:size=160x120:rate=10",
                   "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx264", "-c:a", "aac", "-shortest")
    musica = _gerar(area / "musica.wav", "-f", "lavfi", "-i", "sine=frequency=330:duration=2")
    return {"video": video, "musica": musica}


def _q(indice, area):
    return Quarentena(indice, limite=area, local=lambda a: area / "_quarentena")


# --- imagens (Pillow) ------------------------------------------------------------------


def test_formatos_de_imagem_sem_o_atual(area):
    formatos = [o.formato for o in formatos_possiveis(area / "logo.png", SEM_FFMPEG)]
    assert "png" not in formatos and {"jpg", "webp"} <= set(formatos)


def test_png_para_jpg_com_fundo_branco(area):
    plano = planejar_conversao(area / "logo.png", "jpg", limite=area, ferramentas=SEM_FFMPEG)
    assert plano.destino == area / "logo.jpg" and "fundo branco" in plano.como
    r = converter(plano, ferramentas=SEM_FFMPEG)
    with Image.open(r.destino) as im:
        assert im.format == "JPEG" and im.size == (64, 48)
        r_, g, b = im.getpixel((10, 10))
        assert r_ > 200 and g > 100  # vermelho meio transparente sobre branco = rosado, não preto
    assert (area / "logo.png").exists()  # modo novo: original intacto


def test_aviso_de_transparencia_so_quando_tem(area):
    opaca = planejar_conversao(area / "foto.jpg", "bmp", limite=area, ferramentas=SEM_FFMPEG)
    assert "transparentes" not in opaca.como


def test_nunca_sobrescreve(area):
    (area / "logo.webp").write_bytes(b"ja existia")
    plano = planejar_conversao(area / "logo.png", "webp", limite=area, ferramentas=SEM_FFMPEG)
    assert plano.renomeado and plano.destino.name == "logo (2).webp"
    converter(plano, ferramentas=SEM_FFMPEG)
    assert (area / "logo.webp").read_bytes() == b"ja existia"
    assert (area / "logo (2).webp").exists()


def test_imagem_corrompida_nao_cria_nada(area):
    (area / "quebrada.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"lixo" * 20)
    plano = planejar_conversao(area / "quebrada.png", "jpg", limite=area, ferramentas=SEM_FFMPEG)
    with pytest.raises(ConversaoRecusada):
        converter(plano, ferramentas=SEM_FFMPEG)
    assert not (area / "quebrada.jpg").exists()
    assert not list(area.glob(".faxineiro-convertendo-*"))  # temporário limpo


def test_imagem_grande_demais_e_recusada(area, monkeypatch):
    monkeypatch.setattr(conversor.config, "IMAGEM_MAX_PIXELS", 1000)
    plano = planejar_conversao(area / "foto.jpg", "png", limite=area, ferramentas=SEM_FFMPEG)
    with pytest.raises(ConversaoRecusada, match="grande demais"):
        converter(plano, ferramentas=SEM_FFMPEG)
    assert not (area / "foto.png").exists()


def test_recusa_fora_da_area(area, tmp_path):
    Image.new("RGB", (4, 4)).save(tmp_path / "fora.png")
    with pytest.raises(ConversaoRecusada, match="fora da área"):
        planejar_conversao(tmp_path / "fora.png", "jpg", limite=area, ferramentas=SEM_FFMPEG)


def test_substituir_manda_original_para_quarentena_e_desfaz(area, indice):
    escanear(area, indice)
    q = _q(indice, area)
    plano = planejar_conversao(area / "foto.jpg", "png", modo="substituir", limite=area, ferramentas=SEM_FFMPEG)
    r = converter(plano, indice=indice, quarentena=q, ferramentas=SEM_FFMPEG)
    assert r.destino.exists() and not (area / "foto.jpg").exists()
    assert indice.buscar(str(r.destino)) is not None  # o convertido entrou no índice
    assert len(indice.itens_na_quarentena()) == 1
    q.executar(q.planejar_desfazer(lote=r.lote_id))
    assert (area / "foto.jpg").exists()  # desfazer trouxe o original de volta


def test_substituir_exige_quarentena(area):
    plano = planejar_conversao(area / "foto.jpg", "png", modo="substituir", limite=area, ferramentas=SEM_FFMPEG)
    with pytest.raises(ValueError):
        converter(plano, ferramentas=SEM_FFMPEG)


# --- sem depender do ffmpeg -----------------------------------------------------------------


def test_sem_ffmpeg_audio_e_video_ficam_desligados(area):
    (area / "x.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + bytes(100))
    opcoes = formatos_possiveis(area / "x.mp4", SEM_FFMPEG)
    assert opcoes and not any(o.disponivel for o in opcoes)
    assert "ffmpeg" in opcoes[0].motivo
    with pytest.raises(ConversaoRecusada, match="ffmpeg"):
        planejar_conversao(area / "x.mp4", "mp3", limite=area, ferramentas=SEM_FFMPEG)


@pytest.mark.parametrize("linha, duracao, esperado", [
    ("out_time_us=1500000", 3.0, 0.5), ("out_time_ms=3000000", 3.0, 1.0), ("progress=end", None, 1.0),
    ("frame=10", 3.0, None), ("out_time_us=N/A", 3.0, None), ("out_time_us=9000000", 3.0, 1.0),
])
def test_ler_progresso(linha, duracao, esperado):
    assert ler_progresso(linha, duracao) == esperado


# --- ffmpeg de verdade --------------------------------------------------------------------


@precisa_ffmpeg
def test_extrair_audio_sem_recodificar(area, midia):
    plano = planejar_conversao(midia["video"], EXTRAIR_AUDIO, limite=area)
    assert plano.rapida and plano.argumentos == ["-vn", "-c:a", "copy"]
    assert plano.destino.suffix == ".m4a" and "SEM recodificar" in plano.como
    progresso = []
    r = converter(plano, ao_progredir=progresso.append)
    info = conversor.sondar(FERRAMENTAS.ffprobe, r.destino)
    assert info.codec_audio == "aac" and info.codec_video is None
    assert progresso[-1] == 1.0


@precisa_ffmpeg
def test_video_para_mp3_recodifica(area, midia):
    plano = planejar_conversao(midia["video"], "mp3", limite=area)
    assert not plano.rapida and "recodificar" in plano.como
    r = converter(plano)
    assert conversor.sondar(FERRAMENTAS.ffprobe, r.destino).codec_audio == "mp3"


@precisa_ffmpeg
def test_mp4_para_mkv_so_troca_o_conteiner(area, midia):
    plano = planejar_conversao(midia["video"], "mkv", limite=area)
    assert plano.rapida and plano.argumentos == ["-c", "copy"]
    r = converter(plano)
    info = conversor.sondar(FERRAMENTAS.ffprobe, r.destino)
    assert info.codec_video == "h264" and info.codec_audio == "aac"


@precisa_ffmpeg
def test_wav_para_mp3(area, midia):
    r = converter(planejar_conversao(midia["musica"], "mp3", limite=area))
    assert conversor.sondar(FERRAMENTAS.ffprobe, r.destino).codec_audio == "mp3"


@precisa_ffmpeg
def test_cancelar_nao_deixa_nada(area):
    longo = _gerar(area / "longo.mp4", "-f", "lavfi", "-i", "testsrc=duration=120:size=640x480:rate=25",
                   "-c:v", "libx264", "-preset", "ultrafast")
    plano = planejar_conversao(longo, "webm", limite=area)  # VP9: lento de propósito
    chamadas = {"n": 0}

    def parar():
        chamadas["n"] += 1
        return chamadas["n"] > 3

    r = converter(plano, parar=parar)
    assert r.cancelado and r.destino is None
    assert not (area / "longo.webm").exists()
    assert not list(area.glob(".faxineiro-convertendo-*"))
    assert longo.exists()


@precisa_ffmpeg
def test_video_sem_audio_nao_extrai(area):
    mudo = _gerar(area / "mudo.mp4", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=5", "-c:v", "libx264")
    with pytest.raises(ConversaoRecusada, match="não tem áudio"):
        planejar_conversao(mudo, EXTRAIR_AUDIO, limite=area)
