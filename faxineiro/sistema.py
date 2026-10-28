"""Fase 7C.1 — Raio-X do sistema: o que ocupa Windows, Program Files, ProgramData e AppData.

SÓ LÊ (regra 3, ajustada na 7C): soma os tamanhos pela LISTAGEM das pastas (não abre nenhum
arquivo, não segue atalhos nem junções) e explica em português cada pasta grande, com um selo:
- "seguro limpar": cache ou temporário; o "como" diz por onde (Limpezas seguras, Limpeza do
  Windows, Lixeira) — o Faxineiro nunca apaga direto dentro do Windows ou de Program Files;
- "use o desinstalador": pasta de programa — apagar à mão deixa sobras e quebra o programa;
- "não mexa": parte do Windows ou dados de programas.

Nada vai para o índice: o resultado fica num JSON em dados/ (fora do Git).
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from fnmatch import fnmatchcase
from pathlib import Path

from . import config, disco
from .espaco import arquivos_de_sistema

SEGURO = "seguro limpar"
DESINSTALADOR = "use o desinstalador"
NAO_MEXA = "não mexa"

LIMPEZAS = "Limpezas seguras do Faxineiro"
LIMPEZA_WINDOWS = "Limpeza do Windows (o próprio Windows apaga)"
PROGRAMAS = "Programas instalados → Desinstalar"
LOJA = "Configurações > Aplicativos (apps da Microsoft Store)"
NAVEGADOR = "Limpezas seguras do Faxineiro, com o navegador fechado"

PROFUNDIDADE = 2  # raiz (0) → filhos (1) → netos (2); mais fundo, só as pastas conhecidas
MINIMO = 50 * config.MB  # pasta desconhecida menor que isso não aparece (o tamanho conta no pai)
LINKS = ("Parece maior do que é: muitos arquivos são os MESMOS do System32, vistos em dois lugares "
         "(links). O tamanho real só o Windows mede, com administrador.")


@dataclass(frozen=True)
class Conhecida:
    padrao: str  # começa com {raiz} (a unidade) ou {perfil} (C:\Users\<você>); '*' vale um nível
    selo: str
    explicacao: str
    como: str = ""


# A primeira que casar vale: as mais específicas vêm antes.
CONHECIDAS: tuple[Conhecida, ...] = (
    # --- raiz da unidade ---
    Conhecida(r"{raiz}\Windows", NAO_MEXA, "O Windows: o sistema inteiro. " + LINKS),
    Conhecida(r"{raiz}\Program Files", DESINSTALADOR, "Programas instalados (64 bits). Cada pasta é um programa.",
              PROGRAMAS),
    Conhecida(r"{raiz}\Program Files (x86)", DESINSTALADOR, "Programas instalados (32 bits). Cada pasta é um programa.",
              PROGRAMAS),
    Conhecida(r"{raiz}\ProgramData", NAO_MEXA, "Dados que os programas guardam para todos os usuários do PC "
              "(licenças, bancos de dados, instaladores guardados)."),
    Conhecida(r"{raiz}\Recovery", NAO_MEXA, "Ambiente de recuperação do Windows (para consertar o PC quando não liga)."),
    Conhecida(r"{raiz}\$Recycle.Bin", SEGURO, "A Lixeira (de todos os usuários).", "Esvazie a Lixeira do Windows"),
    Conhecida(r"{raiz}\System Volume Information", NAO_MEXA, "Pontos de restauração e dados internos do Windows. "
              "O Windows não deixa ler; o tamanho aparece em Proteção do Sistema.",
              "Painel de Controle > Sistema > Proteção do Sistema"),
    Conhecida(r"{raiz}\Windows.old", SEGURO, "O Windows anterior, guardado depois de uma atualização grande "
              "(serve para voltar atrás). O Windows apaga sozinho depois de uns dias.", LIMPEZA_WINDOWS),
    Conhecida(r"{raiz}\$Windows.~BT", SEGURO, "Sobra de atualização/instalação do Windows.", LIMPEZA_WINDOWS),
    Conhecida(r"{raiz}\$Windows.~WS", SEGURO, "Sobra de atualização/instalação do Windows.", LIMPEZA_WINDOWS),
    Conhecida(r"{raiz}\$WINDOWS.~TMP", SEGURO, "Sobra de atualização do Windows.", LIMPEZA_WINDOWS),
    Conhecida(r"{raiz}\$WinREAgent", NAO_MEXA, "Temporário da atualização do ambiente de recuperação "
              "(o Windows apaga sozinho)."),
    # --- dentro do Windows ---
    Conhecida(r"{raiz}\Windows\WinSxS", NAO_MEXA, "Armazém de componentes: cópias das peças do Windows, usadas "
              "para reparar e atualizar. " + LINKS, LIMPEZA_WINDOWS + " → limpeza de atualizações"),
    Conhecida(r"{raiz}\Windows\System32", NAO_MEXA, "O coração do Windows."),
    Conhecida(r"{raiz}\Windows\SysWOW64", NAO_MEXA, "Peças do Windows para programas de 32 bits."),
    Conhecida(r"{raiz}\Windows\SoftwareDistribution", SEGURO, "Downloads do Windows Update (já instalados ou "
              "esperando para instalar).", LIMPEZA_WINDOWS),
    Conhecida(r"{raiz}\Windows\Installer", NAO_MEXA, "Cópias dos instaladores (.msi) que o Windows usa para reparar "
              "e desinstalar programas. Apagar à mão quebra as desinstalações."),
    Conhecida(r"{raiz}\Windows\Temp", SEGURO, "Arquivos temporários do Windows e dos instaladores.", LIMPEZA_WINDOWS),
    Conhecida(r"{raiz}\Windows\Logs", SEGURO, "Registros (logs) do Windows e das atualizações.", LIMPEZA_WINDOWS),
    Conhecida(r"{raiz}\Windows\LiveKernelReports", SEGURO, "Relatórios de travamento do Windows (podem ser grandes).",
              LIMPEZA_WINDOWS),
    Conhecida(r"{raiz}\Windows\Minidump", SEGURO, "Relatórios de tela azul.", LIMPEZA_WINDOWS),
    Conhecida(r"{raiz}\Windows\Prefetch", NAO_MEXA, "Ajuda os programas a abrir mais rápido; o Windows cuida sozinho."),
    Conhecida(r"{raiz}\Windows\SystemApps", NAO_MEXA, "Apps que fazem parte do Windows (Iniciar, Configurações...)."),
    Conhecida(r"{raiz}\Windows\Fonts", NAO_MEXA, "As fontes (letras) instaladas."),
    Conhecida(r"{raiz}\Windows\servicing", NAO_MEXA, "Peças que o Windows usa para instalar atualizações."),
    Conhecida(r"{raiz}\Windows\assembly", NAO_MEXA, "Bibliotecas do .NET compartilhadas pelos programas."),
    Conhecida(r"{raiz}\Windows\Microsoft.NET", NAO_MEXA, "O .NET Framework, usado por muitos programas."),
    Conhecida(r"{raiz}\Windows\ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows\DeliveryOptimization",
              SEGURO, "Otimização de entrega: pedaços de atualizações guardados para compartilhar.", LIMPEZA_WINDOWS),
    # --- Program Files ---
    Conhecida(r"{raiz}\Program Files\WindowsApps", NAO_MEXA, "Apps da Microsoft Store. O Windows não deixa ler.", LOJA),
    Conhecida(r"{raiz}\Program Files*\Common Files", NAO_MEXA, "Peças compartilhadas por vários programas."),
    Conhecida(r"{raiz}\Program Files*\Windows Kits", DESINSTALADOR, "Kit de desenvolvimento do Windows (SDK), "
              "instalado junto com o Visual Studio ou ferramentas de programação.", PROGRAMAS),
    Conhecida(r"{raiz}\Program Files*\Windows*", NAO_MEXA, "Parte do Windows."),
    Conhecida(r"{raiz}\Program Files*\Microsoft", NAO_MEXA, "Edge e WebView2: fazem parte do Windows "
              "(muitos apps usam o WebView2 para mostrar telas)."),
    Conhecida(r"{raiz}\Program Files*\Microsoft Update Health Tools", NAO_MEXA, "Parte do Windows Update."),
    Conhecida(r"{raiz}\Program Files*\Internet Explorer", NAO_MEXA, "Parte do Windows."),
    Conhecida(r"{raiz}\Program Files*\ModifiableWindowsApps", NAO_MEXA, "Parte da Microsoft Store."),
    Conhecida(r"{raiz}\Program Files*\Reference Assemblies", NAO_MEXA, "Peças do .NET para programadores."),
    Conhecida(r"{raiz}\Program Files*\Uninstall Information", NAO_MEXA, "Usada pelos desinstaladores."),
    # --- ProgramData ---
    Conhecida(r"{raiz}\ProgramData\Package Cache", NAO_MEXA, "Instaladores guardados (Visual Studio, .NET, "
              "redistribuíveis do C++): o Windows usa para reparar e desinstalar."),
    Conhecida(r"{raiz}\ProgramData\Microsoft\Windows\WER", SEGURO, "Relatórios de erro do Windows.", LIMPEZA_WINDOWS),
    Conhecida(r"{raiz}\ProgramData\Microsoft\Windows Defender", NAO_MEXA, "O antivírus do Windows."),
    Conhecida(r"{raiz}\ProgramData\Microsoft", NAO_MEXA, "Dados do Windows e de programas da Microsoft."),
    # --- AppData (do usuário) ---
    Conhecida(r"{perfil}\AppData", NAO_MEXA, "Configurações e dados dos seus programas (pasta escondida)."),
    Conhecida(r"{perfil}\AppData\Local", NAO_MEXA, "Dados dos programas que ficam só neste PC (caches, "
              "programas instalados só para você)."),
    Conhecida(r"{perfil}\AppData\Roaming", NAO_MEXA, "Configurações dos programas (perfis, contas, extensões)."),
    Conhecida(r"{perfil}\AppData\LocalLow", NAO_MEXA, "Dados de programas em modo restrito (alguns jogos e "
              "navegadores)."),
    Conhecida(r"{perfil}\AppData\Local\Temp", SEGURO, "Seus arquivos temporários: os programas criam e esquecem.",
              LIMPEZAS),
    Conhecida(r"{perfil}\AppData\Local\CrashDumps", SEGURO, "Relatórios de programas que travaram.", LIMPEZAS),
    Conhecida(r"{perfil}\AppData\Local\npm-cache", SEGURO, "Cache do npm (Node.js): pacotes baixados, que ele "
              "baixa de novo se precisar.", LIMPEZAS),
    Conhecida(r"{perfil}\AppData\Local\pip\cache", SEGURO, "Cache do pip (Python): pacotes baixados, que ele "
              "baixa de novo se precisar.", LIMPEZAS),
    Conhecida(r"{perfil}\AppData\Local\Google\Chrome\User Data\*\Cache", SEGURO, "Cache do Chrome (páginas e "
              "imagens guardadas para abrir mais rápido).", NAVEGADOR),
    Conhecida(r"{perfil}\AppData\Local\Google\Chrome\User Data\*\Code Cache", SEGURO, "Cache de scripts do Chrome.",
              NAVEGADOR),
    Conhecida(r"{perfil}\AppData\Local\Google\Chrome\User Data\*\GPUCache", SEGURO, "Cache gráfico do Chrome.",
              NAVEGADOR),
    Conhecida(r"{perfil}\AppData\Local\Microsoft\Edge\User Data\*\Cache", SEGURO, "Cache do Edge (páginas e "
              "imagens guardadas para abrir mais rápido).", NAVEGADOR),
    Conhecida(r"{perfil}\AppData\Local\Microsoft\Edge\User Data\*\Code Cache", SEGURO, "Cache de scripts do Edge.",
              NAVEGADOR),
    Conhecida(r"{perfil}\AppData\Local\Microsoft\Edge\User Data\*\GPUCache", SEGURO, "Cache gráfico do Edge.",
              NAVEGADOR),
    Conhecida(r"{perfil}\AppData\Local\Mozilla\Firefox\Profiles\*\cache2", SEGURO, "Cache do Firefox.", NAVEGADOR),
    Conhecida(r"{perfil}\AppData\Local\Microsoft\Windows\INetCache", SEGURO, "Arquivos temporários de internet "
              "do Windows.", LIMPEZA_WINDOWS),
    Conhecida(r"{perfil}\AppData\Local\Microsoft\Windows\Explorer", SEGURO, "Miniaturas do Explorador (o Windows "
              "refaz quando precisar).", LIMPEZA_WINDOWS),
    Conhecida(r"{perfil}\AppData\Local\D3DSCache", SEGURO, "Cache de sombreadores do DirectX (jogos).",
              LIMPEZA_WINDOWS),
    Conhecida(r"{perfil}\AppData\Local\Packages", NAO_MEXA, "Dados dos apps da Microsoft Store.", LOJA),
    Conhecida(r"{perfil}\AppData\Local\Microsoft\WindowsApps", NAO_MEXA, "Atalhos dos apps da Microsoft Store."),
    Conhecida(r"{perfil}\AppData\Local\Programs", DESINSTALADOR, "Programas instalados só para você (VS Code, "
              "Discord...).", PROGRAMAS),
)

SOBRA = "Se o programa já foi desinstalado, pode ser sobra (o Detetive de pastas vai dizer)."

# Pastas SEM explicação própria: a regra vem do PAI. (padrão do pai, selo, texto com {nome}, como)
POR_PAI: tuple[tuple[str, str, str, str], ...] = (
    (r"{raiz}\Program Files*", DESINSTALADOR, "Programa instalado: {nome}.", PROGRAMAS),
    (r"{perfil}\AppData\Local\Programs", DESINSTALADOR, "Programa instalado só para você: {nome}.", PROGRAMAS),
    (r"{raiz}\ProgramData", NAO_MEXA, "Dados de {nome} para todos os usuários.", SOBRA),
    (r"{perfil}\AppData\Local", NAO_MEXA, "Dados de {nome} (programa ou app).", SOBRA),
    (r"{perfil}\AppData\Roaming", NAO_MEXA, "Configurações de {nome} (programa ou app).", SOBRA),
    (r"{perfil}\AppData\LocalLow", NAO_MEXA, "Dados de {nome} (programa ou jogo).", SOBRA),
    (r"{raiz}\Windows", NAO_MEXA, "Parte do Windows.", ""),
)


@dataclass
class Item:
    caminho: str
    tamanho: int = 0
    arquivos: int = 0
    selo: str = NAO_MEXA
    explicacao: str = ""
    como: str = ""
    conhecida: bool = False
    sem_permissao: bool = False  # o Windows não deixou ler a pasta (ou alguma de dentro)
    arquivo: bool = False  # pagefile.sys, hiberfil.sys...
    filhos: list[Item] = field(default_factory=list)

    @property
    def nome(self) -> str:
        return Path(self.caminho).name or self.caminho


@dataclass
class RaioXSistema:
    unidade: str  # ex.: "C:\\"
    medido_em: str
    usado: int
    itens: list[Item]
    cancelado: bool = False
    pastas_lidas: int = 0

    @property
    def total(self) -> int:
        return sum(i.tamanho for i in self.itens)


@dataclass
class Progresso:
    pastas: int
    bytes: int
    atual: str


class _Parou(Exception):
    pass


def _partes(caminho: str | Path) -> tuple[str, ...]:
    return tuple(p.casefold() for p in Path(caminho).parts)


def _casa(padrao: tuple[str, ...], partes: tuple[str, ...]) -> bool:
    return len(padrao) == len(partes) and all(fnmatchcase(p, q) for p, q in zip(partes, padrao))


class _Medidor:
    def __init__(self, raiz: Path, perfil: Path | None, parar, ao_progredir, minimo: int) -> None:
        self.raiz, self.perfil = raiz, perfil
        self.parar, self.ao_progredir, self.minimo = parar, ao_progredir, minimo
        self.conhecidas = [(p, c) for c in CONHECIDAS if (p := self._expandir(c.padrao))]
        self.por_pai = [(p, regra) for regra in POR_PAI if (p := self._expandir(regra[0]))]
        self.pastas = self.bytes = 0

    def _expandir(self, padrao: str) -> tuple[str, ...] | None:
        cabeca, _, resto = padrao.partition("\\")
        base = {"{raiz}": self.raiz, "{perfil}": self.perfil}[cabeca]
        if base is None:
            return None
        return _partes(base) + tuple(p.casefold() for p in resto.split("\\") if p)

    def _novo(self, caminho: str, partes: tuple[str, ...], ancestral: Item | None) -> Item:
        conhecida = next((c for p, c in self.conhecidas if _casa(p, partes)), None)
        if conhecida:
            return Item(caminho, selo=conhecida.selo, explicacao=conhecida.explicacao, como=conhecida.como,
                        conhecida=True)
        nome = Path(caminho).name
        regra = next((r for p, r in self.por_pai if _casa(p, partes[:-1])), None)
        if regra:
            return Item(caminho, selo=regra[1], explicacao=regra[2].format(nome=nome), como=regra[3])
        if ancestral is not None:  # mais fundo: herda do pai (dentro de Temp continua seguro...)
            return Item(caminho, selo=ancestral.selo, explicacao=f"Parte de {ancestral.nome}.", como=ancestral.como)
        return Item(caminho)

    def _eh_conhecida(self, partes: tuple[str, ...]) -> bool:
        return any(_casa(p, partes) for p, _ in self.conhecidas)

    def medir(self, caminho: str, partes: tuple[str, ...], prof: int,
              ancestral: Item | None) -> tuple[Item | None, int, int, bool]:
        """Mede a pasta inteira: (Item ou None, bytes, arquivos, alguma pasta negada).

        Só vira Item a pasta rasa (até PROFUNDIDADE) ou conhecida; as de dentro só somam no
        tamanho, e as conhecidas lá do fundo (ex.: cache do Chrome) vão para o ancestral mais perto."""
        item = self._novo(caminho, partes, ancestral) if prof <= PROFUNDIDADE or self._eh_conhecida(partes) else None
        dono = item or ancestral
        tamanho = arquivos = 0
        negada = False
        self.pastas += 1
        if self.pastas % 200 == 0:
            if self.parar():
                raise _Parou
            if self.ao_progredir:
                self.ao_progredir(Progresso(self.pastas, self.bytes, caminho))
        try:
            with os.scandir(disco.no_disco(caminho)) as it:
                entradas = list(it)
        except PermissionError:
            entradas, negada = [], True
        except OSError:
            entradas = []
        for e in entradas:
            try:
                if e.is_symlink() or getattr(e, "is_junction", lambda: False)():
                    continue  # atalhos e junções (ex.: "Documents and Settings") apontam para outro lugar
                if e.is_dir(follow_symlinks=False):
                    filho, t, a, n = self.medir(os.path.join(caminho, e.name), partes + (e.name.casefold(),),
                                                prof + 1, dono)
                    tamanho, arquivos, negada = tamanho + t, arquivos + a, negada or n
                    if filho is not None and dono is not None:
                        dono.filhos.append(filho)
                else:
                    t = e.stat(follow_symlinks=False).st_size
                    tamanho, arquivos = tamanho + t, arquivos + 1
                    self.bytes += t
            except OSError:
                continue
        if item is not None:
            item.tamanho, item.arquivos, item.sem_permissao = tamanho, arquivos, negada
        return item, tamanho, arquivos, negada


# Pastas cujas subpastas têm nomes que não dizem nada (códigos do Windows): mostra só o total.
OPACAS = {"winsxs", "installer", "assembly", "package cache", "packages", "systemapps"}


def _podar(item: Item, minimo: int) -> None:
    """Deixa só o que interessa: as conhecidas e as grandes (dentro das opacas, só as conhecidas)."""
    opaca = item.nome.casefold() in OPACAS
    item.filhos = [f for f in item.filhos if f.conhecida or (f.tamanho >= minimo and not opaca)]
    item.filhos.sort(key=lambda f: f.tamanho, reverse=True)
    for f in item.filhos:
        _podar(f, minimo)


def raizes(raiz: Path, perfil: Path | None) -> list[Path]:
    """As pastas de sistema que existem na unidade (pela listagem da raiz) + o AppData do usuário."""
    nomes = {n.casefold() for n in (*config.NOMES_BLOQUEADOS_NA_RAIZ, "$Recycle.Bin", "System Volume Information")}
    achadas: list[Path] = []
    try:
        with os.scandir(raiz) as it:
            achadas = [raiz / e.name for e in it if e.name.casefold() in nomes and e.is_dir(follow_symlinks=False)]
    except OSError:
        pass
    if perfil is not None and config.dentro_da_pasta_teste(perfil, raiz) and (perfil / "AppData").is_dir():
        achadas.append(perfil / "AppData")
    return sorted(achadas, key=lambda p: str(p).casefold())


def medir_sistema(
    unidade: str | Path = config.UNIDADE_DO_SISTEMA,
    *,
    perfil: Path | None = config.PASTA_DO_USUARIO,
    parar: Callable[[], bool] = lambda: False,
    ao_progredir: Callable[[Progresso], None] | None = None,
    minimo: int = MINIMO,
    uso: Callable[[str], tuple[int, int, int]] = shutil.disk_usage,
) -> RaioXSistema:
    """Mede as pastas de sistema de `unidade` ("C:" ou, nos testes, uma pasta qualquer)."""
    texto = str(unidade)
    raiz = Path(texto + "\\" if texto.endswith(":") else texto)
    m = _Medidor(raiz, perfil, parar, ao_progredir, minimo)
    itens: list[Item] = []
    cancelado = False
    try:
        for pasta in raizes(raiz, perfil):
            item = m.medir(str(pasta), _partes(pasta), 0, None)[0]
            _podar(item, minimo)
            itens.append(item)
    except _Parou:
        cancelado = True
    for nome, tamanho in sorted(arquivos_de_sistema(raiz).items()):
        itens.append(Item(str(raiz / nome), tamanho=tamanho, arquivos=1, arquivo=True, conhecida=True,
                          selo=NAO_MEXA, **_ARQUIVOS[nome]))
    itens.sort(key=lambda i: i.tamanho, reverse=True)
    return RaioXSistema(unidade=str(raiz), medido_em=datetime.now().isoformat(timespec="seconds"),
                        usado=uso(str(raiz))[1], itens=itens, cancelado=cancelado, pastas_lidas=m.pastas)


_ARQUIVOS = {
    "pagefile.sys": {"explicacao": "Memória virtual: o Windows usa o disco quando a RAM (4 GB) acaba. "
                     "Neste PC ele é importante.", "como": "Não mexa"},
    "hiberfil.sys": {"explicacao": "Hibernação e inicialização rápida: guarda a memória ao desligar.",
                     "como": "Dá para desligar a hibernação (Ajustes do sistema)"},
    "swapfile.sys": {"explicacao": "Memória virtual dos apps da Microsoft Store.", "como": "Não mexa"},
}  # as mesmas chaves de espaco.ARQUIVOS_DE_SISTEMA (o teste confere)


# --- guardar a última medição (dados/, fora do Git) ------------------------------------------


def arquivo_salvo(unidade: str, pasta: Path | None = None) -> Path:
    letra = "".join(c for c in str(unidade) if c.isalnum())[:1].upper() or "X"
    return (pasta or config.RAIZ_PROJETO / "dados") / f"sistema_{letra}.json"


def salvar(rx: RaioXSistema, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(asdict(rx), ensure_ascii=False), encoding="utf-8")


def _item(d: dict) -> Item:
    return Item(**{**d, "filhos": [_item(f) for f in d.get("filhos", [])]})


def carregar(origem: Path) -> RaioXSistema | None:
    try:
        d = json.loads(origem.read_text(encoding="utf-8"))
        return RaioXSistema(**{**d, "itens": [_item(i) for i in d["itens"]]})
    except (OSError, ValueError, TypeError, KeyError):
        return None
