"""Índice em SQLite. Guarda só dados sobre os arquivos, nunca o conteúdo (regra 4)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

VERSAO_ESQUEMA = 1

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
        self.con.executescript(_ESQUEMA)
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
                hash_parcial = NULL, hash_completo = NULL,
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

    def tamanho_em_disco(self) -> int:
        """Bytes ocupados pelo índice (arquivo principal + WAL + SHM)."""
        total = 0
        for sufixo in ("", "-wal", "-shm"):
            p = Path(str(self.caminho) + sufixo)
            if p.exists():
                total += p.stat().st_size
        return total
