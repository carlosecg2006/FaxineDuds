import itertools

import pytest

from faxineiro.treemap import squarify


def _sobrepoe(a, b) -> bool:
    eps = 1e-6
    return not (a.x + a.largura <= b.x + eps or b.x + b.largura <= a.x + eps
                or a.y + a.altura <= b.y + eps or b.y + b.altura <= a.y + eps)


def test_areas_proporcionais_e_dentro_da_area():
    tamanhos = [500, 250, 125, 100, 25]
    blocos = squarify(tamanhos, 0, 0, 400, 300)
    assert len(blocos) == 5
    total = sum(tamanhos)
    for b in blocos:
        assert b.area == pytest.approx(400 * 300 * tamanhos[b.indice] / total)
        assert b.x >= -1e-6 and b.y >= -1e-6
        assert b.x + b.largura <= 400 + 1e-6 and b.y + b.altura <= 300 + 1e-6
    assert sum(b.area for b in blocos) == pytest.approx(400 * 300)


def test_sem_sobreposicao():
    blocos = squarify([7, 6, 5, 4, 3, 2, 1, 1, 1], 10, 20, 600, 200)
    for a, b in itertools.combinations(blocos, 2):
        assert not _sobrepoe(a, b)


def test_ignora_zeros_e_vazio():
    blocos = squarify([0, 10, -5, 0], 0, 0, 100, 100)
    assert [b.indice for b in blocos] == [1]
    assert squarify([], 0, 0, 100, 100) == []
    assert squarify([1, 2], 0, 0, 0, 100) == []


def test_blocos_quase_quadrados():
    """O "squarified" evita tiras finas: nenhum bloco muito esticado com tamanhos parecidos."""
    blocos = squarify([1] * 16, 0, 0, 400, 400)
    for b in blocos:
        assert max(b.largura / b.altura, b.altura / b.largura) < 2.5
