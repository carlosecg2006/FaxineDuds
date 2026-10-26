"""Compara modelos do Ollama nos mesmos arquivos: tempo, memória e a descrição de cada um.

Usa exatamente o mesmo prompt do app (nome + pasta + começo cortado). Só lê os arquivos;
não grava nada no índice. Resultado em docs/comparacao_modelos.md.

Uso: python ferramentas/comparar_modelos.py qwen2.5:0.5b qwen2.5:1.5b
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from faxineiro.config import CAMINHO_INDICE, PASTA_TESTE  # noqa: E402
from faxineiro.descricoes import TIPOS_COM_TEXTO, montar_prompt, _limpar_resposta  # noqa: E402
from faxineiro.extracao import comeco_do_texto  # noqa: E402
from faxineiro.ia import ClienteOllama, IAIndisponivel  # noqa: E402
from faxineiro.indice import Indice  # noqa: E402
from faxineiro.memoria import MB, memoria_disponivel  # noqa: E402

PASTA = PASTA_TESTE / "Amostras_IA"


class MonitorMemoria:
    """Mede a menor memória disponível enquanto o modelo trabalha."""

    def __init__(self) -> None:
        self.minimo = memoria_disponivel() or 0
        self._parar = threading.Event()
        self._t = threading.Thread(target=self._rodar, daemon=True)

    def _rodar(self) -> None:
        while not self._parar.wait(0.25):
            self.minimo = min(self.minimo, memoria_disponivel() or self.minimo)

    def __enter__(self) -> "MonitorMemoria":
        self._t.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._parar.set()
        self._t.join()


def rodar(modelo: str, linhas) -> dict:
    cliente = ClienteOllama(modelo=modelo)
    antes = (memoria_disponivel() or 0) // MB
    resultados = []
    with MonitorMemoria() as mon:
        for i, linha in enumerate(linhas):
            texto = comeco_do_texto(linha["caminho"], linha["tipo_real"]) if linha["tipo_real"] in TIPOS_COM_TEXTO else None
            inicio = time.monotonic()
            try:
                resposta = _limpar_resposta(cliente.gerar(montar_prompt(linha, texto), timeout=300 if i == 0 else 180))
            except IAIndisponivel as erro:
                resposta = f"(falhou: {erro})"
            resultados.append((linha["nome"], time.monotonic() - inicio, resposta))
            print(f"  [{modelo}] {linha['nome']}: {resultados[-1][1]:.1f} s", flush=True)
    cliente.descarregar()
    time.sleep(2)
    return {"modelo": modelo, "resultados": resultados, "mem_antes": antes,
            "mem_minima": mon.minimo // MB, "mem_depois": (memoria_disponivel() or 0) // MB}


def main(modelos: list[str]) -> int:
    with Indice(CAMINHO_INDICE) as indice:
        prefixo = str(PASTA.resolve()) + "\\"
        linhas = [l for l in indice.todos(prefixo)][:10]
    if len(linhas) < 10:
        print("Rode antes: ferramentas/gerar_amostras.py e python -m faxineiro escanear")
        return 1

    rodadas = []
    for m in modelos:
        print(f"== {m}", flush=True)
        rodadas.append(rodar(m, linhas))

    saida = ["# Comparação de modelos (mesmos 10 arquivos, mesmo prompt do app)", ""]
    saida.append("| Modelo | 1ª resposta (carrega o modelo) | Média das outras 9 | Total | "
                 "RAM disponível antes → mínima → depois |")
    saida.append("|---|---|---|---|---|")
    for r in rodadas:
        tempos = [t for _, t, _ in r["resultados"]]
        saida.append(f"| {r['modelo']} | {tempos[0]:.1f} s | {sum(tempos[1:]) / 9:.1f} s | {sum(tempos):.0f} s | "
                     f"{r['mem_antes']} MB → {r['mem_minima']} MB → {r['mem_depois']} MB |")
    saida += ["", "## Descrições lado a lado", ""]
    saida.append("| Arquivo | " + " | ".join(r["modelo"] for r in rodadas) + " |")
    saida.append("|---|" + "---|" * len(rodadas))
    for i, linha in enumerate(linhas):
        celulas = [f"{r['resultados'][i][2]} *({r['resultados'][i][1]:.0f} s)*".replace("|", "/") for r in rodadas]
        saida.append(f"| {linha['nome']} | " + " | ".join(celulas) + " |")
    texto = "\n".join(saida) + "\n"
    destino = RAIZ / "docs" / "comparacao_modelos.md"
    destino.write_text(texto, encoding="utf-8")
    print()
    print(texto)
    print(f"(salvo em {destino})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["qwen2.5:0.5b", "qwen2.5:1.5b"]))
