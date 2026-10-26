"""Índice em SQLite. Guarda só dados sobre os arquivos, nunca o conteúdo (regra 4)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

VERSAO_ESQUEMA = 3

# Migrações aplicadas em ordem: a chave é a versão que o banco passa a ter.
_MIGRACOES: dict[int, str] = {
    2: """
    ALTER TABLE arquivos ADD COLUMN hash_em TEXT;
    CREATE INDEX IF NOT EXISTS idx_arquivos_hash ON arquivos (hash_completo);
    """,
    # Fase 3: diário de operações (quarentena, restaurar, esvaziar) e histórico.
    3: """
    CREATE TABLE IF NOT EXISTS lotes (
        id        INTEGER PRIMARY KEY,
        tipo      TEXT NOT NULL,
        descricao TEXT,
        criado_em TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS operacoes (
        id            INTEGER PRIMARY KEY,
        lote_id       INTEGER NOT NULL REFERENCES lotes (id),
        tipo          TEXT    NOT NULL,   -- quarentena | restaurar | esvaziar
        origem        TEXT    NOT NULL,
        destino       TEXT    NOT NULL,
        pasta_raiz    TEXT,
        tamanho       INTEGER,
        hash_completo TEXT,
        estado        TEXT    NOT NULL,   -- em_andamento | feita | falhou
        situacao      TEXT,               -- só na quarentena: na_quarentena | restaurado | esvaziado
        ref_operacao  INTEGER REFERENCES operacoes (id),
        criado_em     TEXT    NOT NULL,
        concluido_em  TEXT,
        erro          TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_operacoes_estado ON operacoes (estado);
    CREATE INDEX IF NOT EXISTS idx_operacoes_situacao ON operacoes (situacao);
    """,
}

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS arquivos (
    id               INTEGER PRIMARY KEY,
    caminho          TEXT    NOT NULL UNIQUE,
    pasta_raiz       TEXT    NOT NULL,
    nome             TEXT    NOT NULL,
    extensao         TEXT    NOT NULL,
    tamanho          INTEGER NOT NULL,
    criado_em        TEXT,
    modificado_em    TEXT,
    modificado_ns    INTEGER NOT NULL,
    tipo_real        TEXT,
    categoria        TEXT,
    extensao_confere INTEGER,
    hash_parcial     TEXT,
    hash_completo    TEXT,
    aparelho         TEXT    NOT NULL DEFAULT 'pc',
    conectado        INTEGER NOT NULL DEFAULT 1,
    visto_em         INTEGER NOT NULL,
    indexado_em      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_arquivos_raiz ON arquivos (pasta_raiz);
CREATE INDEX IF NOT EXISTS idx_arquivos_tamanho ON arquivos (tamanho);

CREATE TABLE IF NOT EXISTS varreduras (
    id         INTEGER PRIMARY KEY,
    pasta_raiz TEXT    NOT NULL,
    aparelho   TEXT    NOT NULL,
    inicio     TEXT    NOT NULL,
    fim        TEXT,
    novos      INTEGER DEFAULT 0,
    alterados  INTEGER DEFAULT 0,
    iguais     INTEGER DEFAULT 0,
    removidos  INTEGER DEFAULT 0,
    ignorados  INTEGER DEFAULT 0,
    erros      INTEGER DEFAULT 0
);
"""


@dataclass(frozen=True)
class Registro:
    caminho: str
    pasta_raiz: str
    nome: str
    extensao: str
    tamanho: int
    criado_em: str
    modificado_em: str
    modificado_ns: int
    tipo_real: str
    categoria: str
    extensao_confere: bool
    aparelho: str = "pc"
    conectado: bool = True


class Indice:
    def __init__(self, caminho: str | Path) -> None:
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.caminho)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self._criar_esquema()

    def _criar_esquema(self) -> None:
        versao = self.con.execute("PRAGMA user_version").fetchone()[0]
        if versao > VERSAO_ESQUEMA:
            raise RuntimeError(f"Índice criado por versão mais nova do Faxineiro (esquema {versao}).")
        self.con.executescript(_ESQUEMA)  # cria as tabelas da versão 1, se faltarem
        for nova in range(max(versao, 1) + 1, VERSAO_ESQUEMA + 1):
            self.con.executescript(_MIGRACOES[nova])
            self.con.execute(f"PRAGMA user_version = {nova}")
        self.con.execute(f"PRAGMA user_version = {VERSAO_ESQUEMA}")
        self.con.commit()

    def checkpoint(self) -> None:
        """Passa o conteúdo do WAL para o arquivo principal (tamanho estável e fácil de copiar)."""
        if not self.con.in_transaction:
            self.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def fechar(self) -> None:
        self.checkpoint()
        self.con.close()

    def __enter__(self) -> Indice:
        return self

    def __exit__(self, *_: object) -> None:
        self.fechar()

    # --- varreduras -------------------------------------------------------

    def iniciar_varredura(self, pasta_raiz: str, aparelho: str, inicio: str) -> int:
        cur = self.con.execute(
            "INSERT INTO varreduras (pasta_raiz, aparelho, inicio) VALUES (?, ?, ?)",
            (pasta_raiz, aparelho, inicio),
        )
        self.con.commit()
        return cur.lastrowid

    def finalizar_varredura(self, varredura_id: int, fim: str, **contagens: int) -> None:
        colunas = ", ".join(f"{k} = ?" for k in contagens)
        self.con.execute(
            f"UPDATE varreduras SET fim = ?, {colunas} WHERE id = ?",
            (fim, *contagens.values(), varredura_id),
        )
        self.con.commit()

    # --- arquivos ---------------------------------------------------------

    def assinaturas(self, pasta_raiz: str) -> dict[str, tuple[int, int]]:
        """caminho -> (tamanho, modificado_ns), para decidir o que mudou."""
        linhas = self.con.execute(
            "SELECT caminho, tamanho, modificado_ns FROM arquivos WHERE pasta_raiz = ?",
            (pasta_raiz,),
        )
        return {l["caminho"]: (l["tamanho"], l["modificado_ns"]) for l in linhas}

    def gravar(self, r: Registro, varredura_id: int, agora: str) -> None:
        self.con.execute(
            """
            INSERT INTO arquivos (caminho, pasta_raiz, nome, extensao, tamanho, criado_em,
                modificado_em, modificado_ns, tipo_real, categoria, extensao_confere,
                aparelho, conectado, visto_em, indexado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (caminho) DO UPDATE SET
                pasta_raiz = excluded.pasta_raiz, nome = excluded.nome,
                extensao = excluded.extensao, tamanho = excluded.tamanho,
                criado_em = excluded.criado_em, modificado_em = excluded.modificado_em,
                modificado_ns = excluded.modificado_ns, tipo_real = excluded.tipo_real,
                categoria = excluded.categoria, extensao_confere = excluded.extensao_confere,
                aparelho = excluded.aparelho, conectado = excluded.conectado,
                hash_parcial = NULL, hash_completo = NULL, hash_em = NULL,
                visto_em = excluded.visto_em, indexado_em = excluded.indexado_em
            """,
            (r.caminho, r.pasta_raiz, r.nome, r.extensao, r.tamanho, r.criado_em,
             r.modificado_em, r.modificado_ns, r.tipo_real, r.categoria,
             int(r.extensao_confere), r.aparelho, int(r.conectado), varredura_id, agora),
        )

    def marcar_visto(self, caminhos: list[str], varredura_id: int) -> None:
        self.con.executemany(
            "UPDATE arquivos SET visto_em = ?, conectado = 1 WHERE caminho = ?",
            ((varredura_id, c) for c in caminhos),
        )

    def remover_nao_vistos(self, pasta_raiz: str, varredura_id: int) -> int:
        """Tira do ÍNDICE os arquivos que sumiram da pasta. O arquivo em si não é tocado."""
        cur = self.con.execute(
            "DELETE FROM arquivos WHERE pasta_raiz = ? AND visto_em <> ?",
            (pasta_raiz, varredura_id),
        )
        return cur.rowcount

    def confirmar(self) -> None:
        self.con.commit()

    def buscar(self, caminho: str) -> sqlite3.Row | None:
        return self.con.execute("SELECT * FROM arquivos WHERE caminho = ?", (caminho,)).fetchone()

    def contar(self) -> int:
        return self.con.execute("SELECT COUNT(*) FROM arquivos").fetchone()[0]

    # --- consultas do Raio-X (Fase 2) --------------------------------------
    # `prefixo` é a pasta com separador no fim (ex.: "D:\\x\\"), para pegar subpastas.

    def foi_escaneada(self, pasta: str) -> bool:
        """True se `pasta` (ou uma pasta acima dela) já teve varredura completa."""
        alvo = Path(pasta)
        for (raiz,) in self.con.execute("SELECT DISTINCT pasta_raiz FROM varreduras WHERE fim IS NOT NULL"):
            r = Path(raiz)
            if alvo == r or r in alvo.parents:
                return True
        return False

    def candidatos_duplicados(self, prefixo: str) -> list[sqlite3.Row]:
        """Arquivos não vazios que dividem o tamanho com pelo menos outro (etapa 1)."""
        return self.con.execute(
            """
            WITH daqui AS (
                SELECT * FROM arquivos WHERE substr(caminho, 1, ?) = ? AND tamanho > 0
            )
            SELECT * FROM daqui
            WHERE tamanho IN (SELECT tamanho FROM daqui GROUP BY tamanho HAVING COUNT(*) > 1)
            ORDER BY tamanho DESC, caminho
            """,
            (len(prefixo), prefixo),
        ).fetchall()

    def gravar_hashes(self, arquivo_id: int, parcial: str | None, completo: str | None, agora: str) -> None:
        self.con.execute(
            """UPDATE arquivos SET hash_parcial = COALESCE(?, hash_parcial),
                   hash_completo = COALESCE(?, hash_completo), hash_em = ?
               WHERE id = ?""",
            (parcial, completo, agora, arquivo_id),
        )

    def maiores(self, prefixo: str, limite: int, minimo: int = 0) -> list[sqlite3.Row]:
        return self.con.execute(
            """SELECT * FROM arquivos WHERE substr(caminho, 1, ?) = ? AND tamanho >= ?
               ORDER BY tamanho DESC, caminho LIMIT ?""",
            (len(prefixo), prefixo, minimo, limite),
        ).fetchall()

    def totais_por_categoria(self, prefixo: str) -> list[sqlite3.Row]:
        return self.con.execute(
            """SELECT categoria, COUNT(*) AS quantidade, SUM(tamanho) AS bytes
               FROM arquivos WHERE substr(caminho, 1, ?) = ?
               GROUP BY categoria ORDER BY bytes DESC""",
            (len(prefixo), prefixo),
        ).fetchall()

    def arquivos_vazios(self, prefixo: str) -> list[sqlite3.Row]:
        return self.con.execute(
            "SELECT * FROM arquivos WHERE substr(caminho, 1, ?) = ? AND tamanho = 0 ORDER BY caminho",
            (len(prefixo), prefixo),
        ).fetchall()

    def temporarios(
        self, prefixo: str, extensoes: set[str], prefixos_nome: tuple[str, ...], nomes: set[str]
    ) -> list[sqlite3.Row]:
        return [
            l for l in self.todos(prefixo)
            if l["extensao"] in extensoes
            or l["nome"].startswith(prefixos_nome)
            or l["nome"].casefold() in nomes
        ]

    def todos(self, prefixo: str) -> list[sqlite3.Row]:
        return self.con.execute(
            "SELECT * FROM arquivos WHERE substr(caminho, 1, ?) = ? ORDER BY caminho",
            (len(prefixo), prefixo),
        ).fetchall()

    def remover_arquivo(self, caminho: str) -> sqlite3.Row | None:
        """Tira 1 arquivo do índice e devolve a linha que estava lá."""
        linha = self.buscar(caminho)
        if linha is not None:
            self.con.execute("DELETE FROM arquivos WHERE id = ?", (linha["id"],))
        return linha

    # --- diário de operações (Fase 3) ----------------------------------------

    def criar_lote(self, tipo: str, descricao: str, agora: str) -> int:
        cur = self.con.execute(
            "INSERT INTO lotes (tipo, descricao, criado_em) VALUES (?, ?, ?)", (tipo, descricao, agora)
        )
        return cur.lastrowid

    def registrar_operacao(
        self, *, lote_id: int, tipo: str, origem: str, destino: str, pasta_raiz: str | None,
        tamanho: int | None, hash_completo: str | None, ref_operacao: int | None, agora: str,
    ) -> int:
        """Grava a intenção ANTES de mexer no disco (estado em_andamento) e confirma na hora."""
        cur = self.con.execute(
            """INSERT INTO operacoes (lote_id, tipo, origem, destino, pasta_raiz, tamanho,
                   hash_completo, estado, ref_operacao, criado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'em_andamento', ?, ?)""",
            (lote_id, tipo, origem, destino, pasta_raiz, tamanho, hash_completo, ref_operacao, agora),
        )
        self.con.commit()
        return cur.lastrowid

    def concluir_operacao(self, op_id: int, estado: str, agora: str, erro: str | None = None,
                          situacao: str | None = None) -> None:
        self.con.execute(
            """UPDATE operacoes SET estado = ?, concluido_em = ?, erro = ?,
                   situacao = COALESCE(?, situacao) WHERE id = ?""",
            (estado, agora, erro, situacao, op_id),
        )

    def mudar_situacao(self, op_id: int, situacao: str) -> None:
        self.con.execute("UPDATE operacoes SET situacao = ? WHERE id = ?", (situacao, op_id))

    def operacao(self, op_id: int) -> sqlite3.Row | None:
        return self.con.execute("SELECT * FROM operacoes WHERE id = ?", (op_id,)).fetchone()

    def operacoes_em_andamento(self) -> list[sqlite3.Row]:
        return self.con.execute(
            "SELECT * FROM operacoes WHERE estado = 'em_andamento' ORDER BY id"
        ).fetchall()

    def itens_na_quarentena(self, *, item: int | None = None, lote: int | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM operacoes WHERE tipo = 'quarentena' AND situacao = 'na_quarentena'"
        args: list[int] = []
        if item is not None:
            sql += " AND id = ?"
            args.append(item)
        if lote is not None:
            sql += " AND lote_id = ?"
            args.append(lote)
        return self.con.execute(sql + " ORDER BY id", args).fetchall()

    def lotes_na_quarentena(self) -> list[sqlite3.Row]:
        """Resumo por lote do que ainda está na quarentena: quantidade, bytes e desde quando."""
        return self.con.execute(
            """SELECT lote_id, COUNT(*) AS quantidade, SUM(tamanho) AS bytes,
                      MIN(concluido_em) AS desde
               FROM operacoes WHERE tipo = 'quarentena' AND situacao = 'na_quarentena'
               GROUP BY lote_id ORDER BY lote_id"""
        ).fetchall()

    def tamanho_em_disco(self) -> int:
        """Bytes ocupados pelo índice (arquivo principal + WAL + SHM)."""
        total = 0
        for sufixo in ("", "-wal", "-shm"):
            p = Path(str(self.caminho) + sufixo)
            if p.exists():
                total += p.stat().st_size
        return total
