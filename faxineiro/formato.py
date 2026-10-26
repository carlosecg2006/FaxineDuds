"""Formatação de números e tamanhos para a tela."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path


def ha_quanto_tempo(iso: str, hoje: date | None = None) -> str:
    """'hoje', 'há 1 dia', 'há 12 dias' a partir de uma data ISO."""
    hoje = hoje or date.today()
    dias = (hoje - datetime.fromisoformat(iso).date()).days
    if dias <= 0:
        return "hoje"
    return "há 1 dia" if dias == 1 else f"há {dias} dias"


def formatar_bytes(n: float) -> str:
    for unidade in ("B", "KB", "MB", "GB"):
        if n < 1024 or unidade == "GB":
            return f"{n:.0f} {unidade}" if unidade == "B" else f"{n:.1f} {unidade}"
        n /= 1024
    return f"{n} B"


def formatar_duracao(segundos: float | None) -> str:
    if segundos is None:
        return "calculando..."
    segundos = int(round(segundos))
    if segundos < 60:
        return f"{segundos} s"
    minutos, s = divmod(segundos, 60)
    if minutos < 60:
        return f"{minutos} min {s:02d} s"
    horas, minutos = divmod(minutos, 60)
    return f"{horas} h {minutos:02d} min"


def numero(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def relativo(caminho: str | Path, base: Path) -> str:
    try:
        return str(Path(caminho).relative_to(base))
    except ValueError:
        return str(caminho)
