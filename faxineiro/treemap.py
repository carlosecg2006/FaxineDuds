"""Mapa de blocos (treemap) estilo WinDirStat: cada pasta vira um retângulo com área proporcional
ao tamanho. Algoritmo "squarified" (Bruls, Huizing e van Wijk), que deixa os blocos o mais quadrados
possível — fica fácil de enxergar. Sem Qt aqui: só números, para dar para testar.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Retangulo:
    x: float
    y: float
    largura: float
    altura: float
    indice: int  # posição do item na lista original

    @property
    def area(self) -> float:
        return self.largura * self.altura


def _pior_proporcao(linha: list[float], lado: float) -> float:
    """Quão "esticado" fica o pior retângulo da linha (1 = quadrado perfeito)."""
    soma = sum(linha)
    if soma <= 0 or lado <= 0:
        return float("inf")
    maior, menor = max(linha), min(linha)
    return max(lado * lado * maior / (soma * soma), (soma * soma) / (lado * lado * menor))


def squarify(tamanhos: list[float], x: float, y: float, largura: float, altura: float) -> list[Retangulo]:
    """Divide o retângulo (x, y, largura, altura) em blocos proporcionais a `tamanhos`.

    Tamanhos zero ou negativos são ignorados (não ganham bloco). A ordem de saída segue
    do maior para o menor; `Retangulo.indice` diz a qual item da lista original cada bloco pertence.
    """
    itens = sorted(((t, i) for i, t in enumerate(tamanhos) if t > 0), reverse=True)
    total = sum(t for t, _ in itens)
    if not itens or largura <= 0 or altura <= 0:
        return []
    escala = (largura * altura) / total
    areas = [(t * escala, i) for t, i in itens]

    resultado: list[Retangulo] = []
    while areas:
        lado = min(largura, altura)
        linha: list[tuple[float, int]] = [areas.pop(0)]
        while areas and _pior_proporcao([a for a, _ in linha] + [areas[0][0]], lado) <= _pior_proporcao(
                [a for a, _ in linha], lado):
            linha.append(areas.pop(0))
        soma = sum(a for a, _ in linha)
        if largura >= altura:  # coluna à esquerda
            espessura = soma / altura
            cy = y
            for a, i in linha:
                h = a / espessura
                resultado.append(Retangulo(x, cy, espessura, h, i))
                cy += h
            x += espessura
            largura -= espessura
        else:  # faixa no topo
            espessura = soma / largura
            cx = x
            for a, i in linha:
                w = a / espessura
                resultado.append(Retangulo(cx, y, w, espessura, i))
                cx += w
            y += espessura
            altura -= espessura
    return resultado
