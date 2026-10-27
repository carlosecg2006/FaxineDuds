"""Conversor de arquivos (Fase 5B): imagens com Pillow, áudio e vídeo com ffmpeg.

Igual ao resto do app: primeiro `planejar_conversao()` (a prévia — nada muda no disco), depois
`converter()`. Garantias:
- nunca sobrescreve: se o destino existir, vira "nome (2).ext";
- nunca deixa arquivo pela metade: converte para um temporário oculto na mesma pasta e só
  renomeia no fim; cancelou ou deu erro → o temporário (criado pelo app) some, o original fica;
- confere o resultado antes de aceitar (abre com Pillow / ffprobe);
- modo "substituir": só DEPOIS de conferir, o original vai para a quarentena (Fase 3, com desfazer).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .config import dentro_da_pasta_teste
from .tipos import detectar_tipo

# --- formatos --------------------------------------------------------------------

IMAGEM = {"png": "PNG", "jpg": "JPEG", "webp": "WEBP", "bmp": "BMP", "tiff": "TIFF", "gif": "GIF"}
AUDIO = {
    "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
    "m4a": ["-c:a", "aac", "-b:a", "192k"],
    "ogg": ["-c:a", "libvorbis", "-q:a", "5"],
    "opus": ["-c:a", "libopus", "-b:a", "128k"],
    "wav": ["-c:a", "pcm_s16le"],
    "flac": ["-c:a", "flac"],
}
VIDEO = {
    "mp4": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart"],
    "webm": ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "34", "-row-mt", "1", "-c:a", "libopus", "-b:a", "128k"],
    "mkv": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "160k"],
}
EXTRAIR_AUDIO = "audio"  # alvo especial: tira o áudio do vídeo
# Codec de áudio → contêiner onde ele cabe SEM recodificar (cópia rápida).
CONTEINER_DO_CODEC = {"aac": "m4a", "mp3": "mp3", "opus": "opus", "vorbis": "ogg", "flac": "flac"}
# Contêiner de vídeo que aceita copiar os fluxos como estão (só troca a "caixa").
COPIA_DE_VIDEO = {"mp4": ({"h264", "hevc"}, {"aac", "mp3", None}), "mkv": (None, None)}

ROTULOS = {
    "png": "PNG (sem perda)", "jpg": "JPG (menor, com perda)", "webp": "WebP (bem menor)", "bmp": "BMP",
    "tiff": "TIFF", "gif": "GIF", "mp3": "MP3", "m4a": "M4A (AAC)", "ogg": "OGG (Vorbis)", "opus": "Opus",
    "wav": "WAV (sem compressão)", "flac": "FLAC (sem perda)", "mp4": "MP4 (H.264)", "webm": "WebM (VP9)",
    "mkv": "MKV", EXTRAIR_AUDIO: "Extrair só o áudio",
}


class ConversaoRecusada(Exception):
    pass


# --- ferramentas -------------------------------------------------------------------


@dataclass(frozen=True)
class Ferramentas:
    ffmpeg: Path | None
    ffprobe: Path | None

    @property
    def tem_ffmpeg(self) -> bool:
        return self.ffmpeg is not None and self.ffprobe is not None


def localizar_ffmpeg(externos: Path = config.PASTA_EXTERNOS) -> Ferramentas:
    """Ordem: variável FAXINEIRO_FFMPEG (pasta ou ffmpeg.exe) → externos/ffmpeg → PATH."""
    candidatos: list[Path] = []
    if os.environ.get("FAXINEIRO_FFMPEG"):
        p = Path(os.environ["FAXINEIRO_FFMPEG"])
        candidatos.append(p if p.is_dir() else p.parent)
    candidatos += sorted((externos / "ffmpeg").glob("*/bin"), reverse=True)
    sufixo = ".exe" if sys.platform == "win32" else ""
    for pasta in candidatos:
        ff, fp = pasta / f"ffmpeg{sufixo}", pasta / f"ffprobe{sufixo}"
        if ff.is_file() and fp.is_file():
            return Ferramentas(ff, fp)
    ff, fp = shutil.which("ffmpeg"), shutil.which("ffprobe")
    return Ferramentas(Path(ff) if ff else None, Path(fp) if fp else None)


def _sem_janela() -> dict:
    """No Windows: sem janela preta do console e com prioridade baixa (o PC continua respondendo)."""
    if sys.platform != "win32":
        return {}
    return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS}


@dataclass
class InfoMidia:
    duracao: float | None = None
    codec_video: str | None = None
    codec_audio: str | None = None


def sondar(ffprobe: Path, arquivo: Path) -> InfoMidia:
    """Lê duração e codecs com o ffprobe (não altera nada)."""
    r = subprocess.run(
        [str(ffprobe), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(arquivo)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, **_sem_janela(),
    )
    if r.returncode != 0:
        raise ConversaoRecusada(f"o ffprobe não reconheceu o arquivo ({r.stderr.strip()[:200]})")
    dados = json.loads(r.stdout or "{}")
    info = InfoMidia()
    try:
        info.duracao = float(dados.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        info.duracao = None
    for s in dados.get("streams", []):
        if s.get("codec_type") == "video" and info.codec_video is None and s.get("disposition", {}).get("attached_pic") != 1:
            info.codec_video = s.get("codec_name")
        elif s.get("codec_type") == "audio" and info.codec_audio is None:
            info.codec_audio = s.get("codec_name")
    return info


# --- o que dá para fazer com cada arquivo ---------------------------------------------


@dataclass(frozen=True)
class OpcaoFormato:
    formato: str
    rotulo: str
    disponivel: bool
    motivo: str = ""


def categoria_de(caminho: Path) -> tuple[str, str]:
    """(categoria, tipo real) pelo conteúdo, não pela extensão."""
    t = detectar_tipo(caminho)
    tipo = t.tipo_real
    if t.categoria in ("imagem", "audio", "video"):
        return t.categoria, tipo
    # "heic" e alguns vídeos/áudios o detector pode não classificar: usa a extensão como pista
    ext = caminho.suffix.lower().lstrip(".")
    if ext in ("heic", "heif"):
        return "imagem", ext
    if ext in VIDEO or ext in ("mov", "avi", "wmv", "m4v", "3gp", "flv"):
        return "video", ext
    if ext in AUDIO or ext in ("aac", "wma"):
        return "audio", ext
    return t.categoria, tipo


def formatos_possiveis(caminho: str | Path, ferramentas: Ferramentas | None = None) -> list[OpcaoFormato]:
    caminho = Path(caminho)
    ferramentas = ferramentas or localizar_ffmpeg()
    categoria, tipo = categoria_de(caminho)
    atual = {"jpeg": "jpg", "tif": "tiff"}.get(caminho.suffix.lower().lstrip("."), caminho.suffix.lower().lstrip("."))
    sem_ffmpeg = "precisa do ffmpeg (não encontrado)"
    if categoria == "imagem":
        return [OpcaoFormato(f, ROTULOS[f], True) for f in IMAGEM if f != atual]
    if categoria == "audio":
        return [OpcaoFormato(f, ROTULOS[f], ferramentas.tem_ffmpeg, "" if ferramentas.tem_ffmpeg else sem_ffmpeg)
                for f in AUDIO if f != atual]
    if categoria == "video":
        alvos = [EXTRAIR_AUDIO, *[f for f in VIDEO if f != atual], "mp3", "m4a"]
        return [OpcaoFormato(f, ROTULOS[f], ferramentas.tem_ffmpeg, "" if ferramentas.tem_ffmpeg else sem_ffmpeg)
                for f in alvos]
    return []


# --- prévia -------------------------------------------------------------------------


@dataclass
class PlanoConversao:
    origem: Path
    destino: Path
    formato: str  # extensão final (para EXTRAIR_AUDIO, a do áudio escolhido)
    ferramenta: str  # "pillow" | "ffmpeg"
    modo: str  # "novo" | "substituir"
    como: str  # explicação para a prévia
    argumentos: list[str] = field(default_factory=list)  # ffmpeg: o que vai entre a entrada e a saída
    rapida: bool = False  # cópia sem recodificar
    duracao: float | None = None
    renomeado: bool = False


def _tem_transparencia(caminho: Path) -> bool:
    """Lê só o cabeçalho da imagem (não carrega os pixels)."""
    try:
        from PIL import Image

        with Image.open(caminho) as im:
            return im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
    except Exception:
        return False


def nome_livre(destino: Path) -> tuple[Path, bool]:
    """Nunca sobrescreve: 'video.mp4' → 'video (2).mp4' → 'video (3).mp4'..."""
    if not destino.exists():
        return destino, False
    n = 2
    while True:
        candidato = destino.with_name(f"{destino.stem} ({n}){destino.suffix}")
        if not candidato.exists():
            return candidato, True
        n += 1


def planejar_conversao(
    caminho: str | Path,
    formato: str,
    *,
    modo: str = "novo",
    limite: Path = config.PASTA_TESTE,
    ferramentas: Ferramentas | None = None,
) -> PlanoConversao:
    """Monta a prévia. Levanta ConversaoRecusada se não der para converter."""
    origem = Path(caminho).resolve()
    if modo not in ("novo", "substituir"):
        raise ValueError("modo deve ser 'novo' ou 'substituir'")
    if not origem.is_file():
        raise ConversaoRecusada("arquivo não encontrado")
    if not dentro_da_pasta_teste(origem, limite):
        raise ConversaoRecusada(f"fora da área permitida ({limite})")
    limite_r = Path(limite).resolve()
    if any(config.Bloqueios().bloqueada(p) for p in origem.parents if limite_r in p.parents):
        raise ConversaoRecusada("dentro de pasta bloqueada (regra 3): não mexo")
    ferramentas = ferramentas or localizar_ffmpeg()
    opcoes = {o.formato: o for o in formatos_possiveis(origem, ferramentas)}
    if formato not in opcoes:
        raise ConversaoRecusada(f"não sei converter {origem.name} para '{formato}'")
    if not opcoes[formato].disponivel:
        raise ConversaoRecusada(opcoes[formato].motivo)

    categoria, _ = categoria_de(origem)
    if categoria == "imagem":
        destino, renomeado = nome_livre(origem.with_suffix("." + formato))
        como = f"converter a imagem para {ROTULOS[formato]} (Pillow)"
        if formato in ("jpg", "bmp") and _tem_transparencia(origem):
            como += "; as partes transparentes viram fundo branco"
        return PlanoConversao(origem, destino, formato, "pillow", modo, como, renomeado=renomeado)

    info = sondar(ferramentas.ffprobe, origem)
    rapida = False
    if formato == EXTRAIR_AUDIO or (categoria == "video" and formato in AUDIO):
        if info.codec_audio is None:
            raise ConversaoRecusada("este vídeo não tem áudio")
        if formato == EXTRAIR_AUDIO:
            alvo = CONTEINER_DO_CODEC.get(info.codec_audio, "mp3")
        else:
            alvo = formato
        rapida = CONTEINER_DO_CODEC.get(info.codec_audio) == alvo
        argumentos = ["-vn", "-c:a", "copy"] if rapida else ["-vn", *AUDIO[alvo]]
        como = (f"extrair o áudio ({info.codec_audio}) SEM recodificar — cópia rápida" if rapida
                else f"extrair o áudio e recodificar de {info.codec_audio} para {ROTULOS[alvo]}")
    elif categoria == "audio":
        alvo = formato
        argumentos = ["-vn", *AUDIO[alvo]]
        como = f"recodificar o áudio ({info.codec_audio}) para {ROTULOS[alvo]}"
    else:  # vídeo → vídeo
        alvo = formato
        videos_ok, audios_ok = COPIA_DE_VIDEO.get(alvo, (set(), set()))
        rapida = alvo in COPIA_DE_VIDEO and (videos_ok is None or info.codec_video in videos_ok) and (
            audios_ok is None or info.codec_audio in audios_ok)
        argumentos = ["-c", "copy"] if rapida else list(VIDEO[alvo])
        como = (f"só trocar o contêiner para {ROTULOS[alvo]} (copia os fluxos, rápido)" if rapida
                else f"recodificar o vídeo ({info.codec_video}) para {ROTULOS[alvo]} — pode demorar")
    destino, renomeado = nome_livre(origem.with_suffix("." + alvo))
    return PlanoConversao(origem, destino, alvo, "ffmpeg", modo, como, argumentos, rapida, info.duracao, renomeado)


# --- executar -----------------------------------------------------------------------


@dataclass
class ResultadoConversao:
    destino: Path | None = None
    segundos: float = 0.0
    cancelado: bool = False
    lote_id: int | None = None  # modo substituir: lote da quarentena (para desfazer)
    aviso: str = ""


def _temporario(destino: Path) -> Path:
    return destino.with_name(f".faxineiro-convertendo-{uuid.uuid4().hex[:8]}{destino.suffix}")


def _limpar(temp: Path) -> None:
    """Remove só o temporário que o próprio conversor criou (nunca um arquivo do usuário)."""
    if temp.name.startswith(".faxineiro-convertendo-") and temp.exists():
        temp.unlink()


def _converter_imagem(plano: PlanoConversao, temp: Path) -> None:
    from PIL import Image

    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except ImportError:  # sem HEIC: o resto funciona
        pass
    Image.MAX_IMAGE_PIXELS = config.IMAGEM_MAX_PIXELS
    try:
        with Image.open(plano.origem) as im:
            im.seek(0)  # GIF animado: o 1º quadro
            if plano.formato == "jpg" and (im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)):
                im = im.convert("RGBA")
                fundo = Image.new("RGB", im.size, "white")
                fundo.paste(im, mask=im.getchannel("A"))
                im = fundo
            elif plano.formato in ("jpg", "bmp") and im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            opcoes = {"quality": 90} if plano.formato in ("jpg", "webp") else {}
            im.save(temp, IMAGEM[plano.formato], **opcoes)
    except Image.DecompressionBombError as erro:
        raise ConversaoRecusada("imagem grande demais para converter com segurança neste PC") from erro
    except OSError as erro:
        raise ConversaoRecusada(f"não consegui ler a imagem ({erro})") from erro
    with Image.open(temp) as conferir:
        conferir.verify()


def ler_progresso(linha: str, duracao: float | None) -> float | None:
    """Uma linha do `-progress pipe:1` do ffmpeg → fração de 0 a 1 (None se a linha não diz)."""
    chave, _, valor = linha.strip().partition("=")
    if chave == "progress" and valor == "end":
        return 1.0
    if chave in ("out_time_us", "out_time_ms") and duracao:
        try:
            return max(0.0, min(1.0, int(valor) / 1_000_000 / duracao))  # os dois vêm em microssegundos
        except ValueError:
            return None
    return None


def _converter_ffmpeg(plano: PlanoConversao, temp: Path, ferramentas: Ferramentas,
                      parar: Callable[[], bool], ao_progredir) -> bool:
    """Devolve False se foi cancelado."""
    cmd = [str(ferramentas.ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "error", "-threads",
           str(config.FFMPEG_THREADS), "-i", str(plano.origem), *plano.argumentos,
           "-progress", "pipe:1", "-nostats", str(temp)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", **_sem_janela())
    assert proc.stdout is not None
    for linha in proc.stdout:
        if parar():
            proc.kill()
            proc.wait()
            return False
        fracao = ler_progresso(linha, plano.duracao)
        if fracao is not None and ao_progredir:
            ao_progredir(fracao)
    erro = proc.stderr.read() if proc.stderr else ""
    if proc.wait() != 0:
        raise ConversaoRecusada(f"o ffmpeg falhou: {erro.strip()[:300]}")
    info = sondar(ferramentas.ffprobe, temp)  # conferência: o resultado abre e tem conteúdo
    if info.codec_audio is None and info.codec_video is None:
        raise ConversaoRecusada("o arquivo convertido não tem áudio nem vídeo")
    return True


def converter(
    plano: PlanoConversao,
    *,
    indice=None,
    quarentena=None,
    parar: Callable[[], bool] = lambda: False,
    ao_progredir: Callable[[float], None] | None = None,
    ferramentas: Ferramentas | None = None,
) -> ResultadoConversao:
    """Executa a conversão planejada. `indice` → o novo arquivo entra no índice;
    `quarentena` (obrigatória no modo substituir) → o original vai para a quarentena."""
    if plano.modo == "substituir" and quarentena is None:
        raise ValueError("modo substituir precisa da quarentena (para dar para desfazer)")
    ferramentas = ferramentas or localizar_ffmpeg()
    resultado = ResultadoConversao()
    inicio = time.monotonic()
    temp = _temporario(plano.destino)
    try:
        if plano.ferramenta == "pillow":
            _converter_imagem(plano, temp)
            if ao_progredir:
                ao_progredir(1.0)
        elif not _converter_ffmpeg(plano, temp, ferramentas, parar, ao_progredir):
            resultado.cancelado = True
            return resultado
        if not temp.exists() or temp.stat().st_size == 0:
            raise ConversaoRecusada("a conversão não gerou nada")
        destino, _ = nome_livre(plano.destino)  # alguém criou um arquivo com o nome enquanto convertia?
        os.rename(temp, destino)  # mesma pasta: instantâneo; nunca sobrescreve (o Windows recusa)
        resultado.destino = destino
    finally:
        _limpar(temp)
    resultado.segundos = time.monotonic() - inicio

    if indice is not None:
        from .scanner import indexar_arquivo

        linha = indice.buscar(str(plano.origem))
        indexar_arquivo(destino, indice, linha["pasta_raiz"] if linha else str(destino.parent))
        indice.confirmar()
    if plano.modo == "substituir":
        r = quarentena.executar(quarentena.planejar_mover([plano.origem], f"substituído por {destino.name}"))
        resultado.lote_id = r.lote_id
        if r.falhas:
            resultado.aviso = f"convertido, mas o original não foi para a quarentena: {r.falhas[0][1]}"
    return resultado
