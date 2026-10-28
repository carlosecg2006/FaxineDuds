from .explorador import TelaExplorador
from .faxina import TelaFaxina
from .ia import TelaIA
from .inicio import TelaInicio
from .organizar import TelaOrganizar
from .limpezas import TelaLimpezas
from .programas import TelaProgramas
from .quarentena import TelaQuarentena
from .sistema import TelaSistema

TELAS = [
    ("Início", TelaInicio),
    ("Explorador", TelaExplorador),
    ("Faxina", TelaFaxina),
    ("Organizar", TelaOrganizar),
    ("Quarentena", TelaQuarentena),
    ("Sistema", TelaSistema),
    ("Programas", TelaProgramas),
    ("Limpezas", TelaLimpezas),
    ("IA", TelaIA),
]
