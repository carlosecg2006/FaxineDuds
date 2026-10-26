"""Cliente de IA falso: respostas programadas, sem depender do Ollama real."""

from __future__ import annotations

import json
from collections.abc import Callable

from faxineiro.ia import IAIndisponivel, IATempoEsgotado, StatusIA

MB = 1024 * 1024


class ClienteFalso:
    def __init__(
        self,
        *,
        ligado: bool = True,
        visao: str | None = None,
        falhar: Callable[[str], bool] = lambda prompt: False,
        indisponivel: bool = False,
        pasta: Callable[[str], str] = lambda prompt: "Documentos/Geral",
        modelo: str = "qwen2.5:0.5b",
        tamanho_modelo: int = 400 * MB,
        ja_carregado: bool = True,  # carregado = não precisa de memória nova (testes não dependem da RAM)
    ) -> None:
        self.ligado = ligado
        self.visao = visao
        self.falhar = falhar
        self.indisponivel = indisponivel
        self.pasta = pasta
        self.modelo = modelo
        self.tamanho_modelo = tamanho_modelo
        self.ja_carregado = ja_carregado
        self.chamadas: list[dict] = []
        self.descarregamentos = 0

    def status(self) -> StatusIA:
        if not self.ligado:
            return StatusIA(ligado=False, erro="conexão recusada")
        modelos = [self.modelo] + ([self.visao] if self.visao else [])
        return StatusIA(ligado=True, versao="falsa", modelos=modelos, modelo_texto=self.modelo,
                        modelo_visao=self.visao, tamanhos={self.modelo: self.tamanho_modelo},
                        carregados=[self.modelo] if self.ja_carregado else [])

    def gerar(self, prompt, *, timeout=60, imagens=None, modelo=None, formato_json=False, max_tokens=80):
        self.chamadas.append({"prompt": prompt, "imagens": imagens, "modelo": modelo, "timeout": timeout,
                              "formato_json": formato_json})
        if self.indisponivel:
            raise IAIndisponivel("Ollama não respondeu (conexão recusada)")
        if self.falhar(prompt):
            raise IATempoEsgotado(f"sem resposta em {timeout:.0f} s")
        if formato_json:
            return json.dumps({"pasta": self.pasta(prompt)})
        if imagens:
            return "Foto de uma praia ensolarada"
        return f"Descrição gerada pela IA número {len(self.chamadas)}"

    def descarregar(self, modelo=None) -> None:
        self.descarregamentos += 1

    @property
    def prompts(self) -> list[str]:
        return [c["prompt"] for c in self.chamadas]
