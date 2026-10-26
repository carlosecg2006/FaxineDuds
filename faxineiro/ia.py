"""Cliente do Ollama. Só conversa com o próprio PC (localhost): nenhum conteúdo sai da máquina."""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlparse

from . import config
from .memoria import MB, memoria_disponivel

MODELO_TEXTO = config.MODELO_IA
ENDERECO_PADRAO = "http://127.0.0.1:11434"
HOSTS_LOCAIS = {"127.0.0.1", "localhost", "::1", "[::1]"}


class IAIndisponivel(Exception):
    """Ollama desligado, recusou a conexão ou respondeu com erro."""


class IATempoEsgotado(IAIndisponivel):
    """A resposta passou do tempo limite."""


class EnderecoNaoLocal(Exception):
    """Tentativa de usar um Ollama fora deste PC (bloqueado: nada pode sair da máquina)."""


@dataclass
class StatusIA:
    ligado: bool
    versao: str = ""
    modelos: list[str] = field(default_factory=list)
    modelo_texto: str | None = None
    modelo_visao: str | None = None
    tamanhos: dict[str, int] = field(default_factory=dict)  # bytes do arquivo de cada modelo
    carregados: list[str] = field(default_factory=list)  # modelos já na memória do Ollama
    erro: str = ""


def endereco_local(endereco: str | None = None) -> str:
    """Resolve o endereço do Ollama e garante que é deste PC."""
    endereco = (endereco or os.environ.get("OLLAMA_HOST") or ENDERECO_PADRAO).strip()
    if "://" not in endereco:
        endereco = "http://" + endereco
    url = urlparse(endereco)
    host = (url.hostname or "").lower()
    if host in ("0.0.0.0", ""):
        host = "127.0.0.1"
    if host not in HOSTS_LOCAIS:
        raise EnderecoNaoLocal(f"O Ollama precisa estar neste PC; recusado: {endereco}")
    porta = url.port or 11434
    host_url = f"[{host.strip('[]')}]" if ":" in host.strip("[]") else host
    return f"http://{host_url}:{porta}"


class ClienteOllama:
    def __init__(self, endereco: str | None = None, modelo: str | None = None, num_thread: int | None = None,
                 num_ctx: int = config.IA_NUM_CTX, keep_alive: str = config.IA_KEEP_ALIVE):
        self.base = endereco_local(endereco)
        self.modelo = modelo or MODELO_TEXTO
        # Todos os núcleos: com pouca RAM, terminar rápido e liberar a memória é o que mais ajuda.
        self.num_thread = num_thread or (os.cpu_count() or 1)
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive

    def _pedir(self, caminho: str, dados: dict | None, timeout: float) -> dict:
        corpo = json.dumps(dados).encode("utf-8") if dados is not None else None
        req = urllib.request.Request(
            self.base + caminho, data=corpo,
            headers={"Content-Type": "application/json"}, method="POST" if corpo else "GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (TimeoutError, socket.timeout) as erro:
            raise IATempoEsgotado(f"sem resposta em {timeout:.0f} s") from erro
        except urllib.error.URLError as erro:
            if isinstance(erro.reason, (TimeoutError, socket.timeout)):
                raise IATempoEsgotado(f"sem resposta em {timeout:.0f} s") from erro
            raise IAIndisponivel(f"Ollama não respondeu ({erro.reason})") from erro
        except (OSError, ValueError) as erro:
            raise IAIndisponivel(f"Ollama não respondeu ({erro})") from erro

    def status(self) -> StatusIA:
        try:
            versao = self._pedir("/api/version", None, 5).get("version", "")
            tags = self._pedir("/api/tags", None, 5).get("models", [])
        except IAIndisponivel as erro:
            return StatusIA(ligado=False, erro=str(erro))
        modelos = [m["name"] for m in tags]
        st = StatusIA(ligado=True, versao=versao, modelos=modelos,
                      tamanhos={m["name"]: int(m.get("size") or 0) for m in tags})
        try:
            st.carregados = [m["name"] for m in self._pedir("/api/ps", None, 5).get("models", [])]
        except IAIndisponivel:
            pass
        if self.modelo in modelos:
            st.modelo_texto = self.modelo
        for nome in modelos:
            if self.tem_visao(nome):
                st.modelo_visao = nome
                break
        return st

    def tem_visao(self, modelo: str) -> bool:
        try:
            info = self._pedir("/api/show", {"model": modelo}, 10)
        except IAIndisponivel:
            return False
        return "vision" in info.get("capabilities", [])

    def gerar(
        self,
        prompt: str,
        *,
        timeout: float = 60,
        imagens: list[str] | None = None,
        modelo: str | None = None,
        formato_json: bool = False,
        max_tokens: int = 80,
    ) -> str:
        dados: dict = {
            "model": modelo or self.modelo,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": 0.2, "num_predict": max_tokens, "num_thread": self.num_thread,
                        "num_ctx": self.num_ctx},
        }
        if imagens:
            dados["images"] = imagens  # base64; vai só para o Ollama local
        if formato_json:
            dados["format"] = "json"
        resposta = self._pedir("/api/generate", dados, timeout)
        return (resposta.get("response") or "").strip()

    def descarregar(self, modelo: str | None = None) -> None:
        """Pede ao Ollama para tirar o modelo da memória agora (keep_alive = 0)."""
        try:
            self._pedir("/api/generate", {"model": modelo or self.modelo, "keep_alive": 0}, 15)
        except IAIndisponivel:
            pass


def memoria_necessaria(st: StatusIA, modelo: str) -> int:
    """Quanto o modelo precisa de RAM livre para carregar (0 se já está carregado)."""
    if modelo in st.carregados:
        return 0
    return int(st.tamanhos.get(modelo, 0) * config.IA_FATOR_MEMORIA) + config.IA_MARGEM_MEMORIA


def avaliar_ia(cliente, memoria=memoria_disponivel) -> tuple[StatusIA, bool, str | None]:
    """Decide se dá para usar a IA agora. Devolve (status, usar, aviso)."""
    if cliente is None:
        return StatusIA(ligado=False, erro="sem cliente de IA"), False, "IA indisponível: usando só regras."
    st = cliente.status()
    if not st.ligado:
        return st, False, f"Ollama desligado ({st.erro}). Usando só regras; o que precisa de IA fica para revisar."
    if not st.modelo_texto:
        return st, False, (f"O modelo {cliente.modelo} não está instalado (rode: ollama pull {cliente.modelo}). "
                           "Usando só regras.")
    livre = memoria()
    precisa = memoria_necessaria(st, cliente.modelo)
    if livre is not None and livre < precisa:
        return st, False, (f"Pouca memória livre ({livre // MB} MB; o modelo {cliente.modelo} precisa de "
                           f"~{precisa // MB} MB). Usando só regras para não travar o PC. "
                           "Feche alguns programas e rode de novo.")
    return st, True, None
