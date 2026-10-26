from .explorador import TelaExplorador
from .faxina import TelaFaxina
from .ia import TelaIA
from .inicio import TelaInicio
from .organizar import TelaOrganizar
from .quarentena import TelaQuarentena

TELAS = [
    ("Início", TelaInicio),
    ("Explorador", TelaExplorador),
    ("Faxina", TelaFaxina),
    ("Organizar", TelaOrganizar),
    ("Quarentena", TelaQuarentena),
    ("IA", TelaIA),
]
