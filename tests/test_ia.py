import json
import socket
import urllib.error

import pytest

from faxineiro import ia
from faxineiro.ia import ClienteOllama, EnderecoNaoLocal, IAIndisponivel, IATempoEsgotado, endereco_local


@pytest.mark.parametrize("endereco", [None, "127.0.0.1:11434", "http://localhost:11434", "0.0.0.0", "[::1]:11434"])
def test_aceita_so_enderecos_locais(endereco, monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert endereco_local(endereco).startswith("http://")


@pytest.mark.parametrize("endereco", ["http://192.168.0.10:11434", "https://api.exemplo.com", "meuservidor:11434"])
def test_recusa_enderecos_de_fora(endereco):
    with pytest.raises(EnderecoNaoLocal):
        endereco_local(endereco)


def test_recusa_ollama_host_remoto(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://10.0.0.5:11434")
    with pytest.raises(EnderecoNaoLocal):
        ClienteOllama()


def _respostas_falsas(monkeypatch, cliente, tabela):
    def pedir(caminho, dados, timeout):
        chave = (caminho, (dados or {}).get("model"))
        valor = tabela.get(chave, tabela.get((caminho, None)))
        if isinstance(valor, Exception):
            raise valor
        return valor

    monkeypatch.setattr(cliente, "_pedir", pedir)


def test_status_com_visao(monkeypatch):
    c = ClienteOllama("127.0.0.1", modelo="qwen2.5:3b")
    _respostas_falsas(monkeypatch, c, {
        ("/api/version", None): {"version": "0.40.11"},
        ("/api/ps", None): {"models": []},
        ("/api/tags", None): {"models": [{"name": "qwen2.5:3b"}, {"name": "llava:7b"}]},
        ("/api/show", "qwen2.5:3b"): {"capabilities": ["completion", "tools"]},
        ("/api/show", "llava:7b"): {"capabilities": ["completion", "vision"]},
    })
    st = c.status()
    assert st.ligado and st.versao == "0.40.11"
    assert st.modelo_texto == "qwen2.5:3b"
    assert st.modelo_visao == "llava:7b"


def test_status_sem_visao(monkeypatch):
    c = ClienteOllama("127.0.0.1")
    _respostas_falsas(monkeypatch, c, {
        ("/api/version", None): {"version": "0.40.11"},
        ("/api/ps", None): {"models": []},
        ("/api/tags", None): {"models": [{"name": "qwen2.5:3b"}]},
        ("/api/show", None): {"capabilities": ["completion", "tools"]},
    })
    assert c.status().modelo_visao is None


def test_status_desligado(monkeypatch):
    c = ClienteOllama("127.0.0.1")
    _respostas_falsas(monkeypatch, c, {("/api/version", None): IAIndisponivel("conexão recusada")})
    st = c.status()
    assert not st.ligado and "recusada" in st.erro


def test_timeout_vira_excecao_propria(monkeypatch):
    def demora(*a, **k):
        raise socket.timeout("timed out")

    monkeypatch.setattr(ia.urllib.request, "urlopen", demora)
    with pytest.raises(IATempoEsgotado):
        ClienteOllama("127.0.0.1").gerar("oi", timeout=1)


def test_conexao_recusada_vira_indisponivel(monkeypatch):
    def recusa(*a, **k):
        raise urllib.error.URLError(ConnectionRefusedError(10061, "recusada"))

    monkeypatch.setattr(ia.urllib.request, "urlopen", recusa)
    with pytest.raises(IAIndisponivel) as erro:
        ClienteOllama("127.0.0.1").gerar("oi")
    assert not isinstance(erro.value, IATempoEsgotado)


MB = 1024 * 1024


def test_memoria_necessaria_e_avaliar():
    from faxineiro.ia import StatusIA, avaliar_ia, memoria_necessaria

    st = StatusIA(ligado=True, modelos=["qwen2.5:0.5b"], modelo_texto="qwen2.5:0.5b",
                  tamanhos={"qwen2.5:0.5b": 400 * MB})
    assert 600 * MB < memoria_necessaria(st, "qwen2.5:0.5b") < 800 * MB
    st.carregados = ["qwen2.5:0.5b"]
    assert memoria_necessaria(st, "qwen2.5:0.5b") == 0  # já carregado: não precisa de mais

    class C:
        modelo = "qwen2.5:0.5b"

        def status(self):
            return StatusIA(ligado=True, modelos=[self.modelo], modelo_texto=self.modelo,
                            tamanhos={self.modelo: 400 * MB})

    _, pode, aviso = avaliar_ia(C(), memoria=lambda: 300 * MB)
    assert not pode and "Pouca memória livre (300 MB" in aviso
    _, pode, aviso = avaliar_ia(C(), memoria=lambda: 2000 * MB)
    assert pode and aviso is None
    _, pode, _ = avaliar_ia(C(), memoria=lambda: None)  # não sabe medir: deixa tentar
    assert pode
    _, pode, aviso = avaliar_ia(None)
    assert not pode


def test_modelo_padrao_e_configuravel(monkeypatch):
    from faxineiro import config

    assert config.MODELO_IA == "qwen2.5:0.5b" or "FAXINEIRO_MODELO" in __import__("os").environ
    assert ClienteOllama("127.0.0.1", modelo="qwen2.5:3b").modelo == "qwen2.5:3b"


def test_descarregar_manda_keep_alive_zero(monkeypatch):
    c = ClienteOllama("127.0.0.1")
    pedidos = []
    monkeypatch.setattr(c, "_pedir", lambda caminho, dados, timeout: pedidos.append((caminho, dados)) or {})
    c.descarregar()
    assert pedidos == [("/api/generate", {"model": c.modelo, "keep_alive": 0})]


def test_gerar_monta_pedido_local_com_threads(monkeypatch):
    enviados = {}

    class Resposta:
        def __init__(self, req):
            enviados["url"] = req.full_url
            enviados["corpo"] = json.loads(req.data)

        def read(self):
            return json.dumps({"response": "  uma descrição  "}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ia.urllib.request, "urlopen", lambda req, timeout: Resposta(req))
    c = ClienteOllama("127.0.0.1")
    assert c.gerar("descreva", formato_json=True) == "uma descrição"
    assert enviados["url"].startswith("http://127.0.0.1:11434/")
    assert enviados["corpo"]["options"]["num_thread"] == (__import__("os").cpu_count() or 1)  # todos os núcleos
    assert enviados["corpo"]["options"]["num_ctx"] == 1024  # contexto pequeno = pouca memória
    assert enviados["corpo"]["keep_alive"] == "30s"  # solta a memória logo
    assert enviados["corpo"]["format"] == "json"
    assert enviados["corpo"]["stream"] is False
