"""Estado e inventário em SQLite (executor único; WAL; transações curtas).

Tabelas:
- execucoes: uma linha por execução (modo, filtros, janela, status).
- descoberta_paginas: evidência da enumeração (página, cursor, protocolos, total exibido).
- processos: estado por protocolo + identificação capturada + pasta.
- pastas: mapa pasta -> protocolo (UNIQUE) para detectar colisões (EX-04, CA-03).
- itens: estado por item (histórico/anexo) com identidade estável.
- versoes: cada conteúdo distinto confirmado no destino (nunca sobrescreve; CA-07).
- eventos: trilha de auditoria de todas as transições (CA-12).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from .models import EstadoItem, EstadoProcesso

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS execucoes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  modo TEXT NOT NULL, filtros TEXT, inicio TEXT NOT NULL, fim TEXT,
  status TEXT NOT NULL, resumo TEXT
);
CREATE TABLE IF NOT EXISTS descoberta_paginas (
  id INTEGER PRIMARY KEY AUTOINCREMENT, execucao_id INTEGER NOT NULL REFERENCES execucoes(id),
  pagina INTEGER NOT NULL, cursor TEXT, total_exibido INTEGER, protocolos TEXT NOT NULL,
  anomalia TEXT, registrado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS processos (
  protocolo TEXT PRIMARY KEY, id_interno TEXT, estado TEXT NOT NULL,
  identificacao TEXT, pasta TEXT, descoberto_em TEXT NOT NULL, ultima_execucao INTEGER,
  primeiro_erro TEXT, ultimo_erro TEXT, codigo_excecao TEXT, tentativas INTEGER NOT NULL DEFAULT 0,
  listagem_completa INTEGER, atualizado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pastas (
  pasta TEXT PRIMARY KEY, protocolo TEXT NOT NULL REFERENCES processos(protocolo)
);
CREATE TABLE IF NOT EXISTS itens (
  chave TEXT PRIMARY KEY, protocolo TEXT NOT NULL REFERENCES processos(protocolo),
  tipo TEXT NOT NULL, id_origem TEXT, nome_original TEXT, contexto TEXT, ordinal INTEGER,
  tamanho_origem INTEGER, data_origem TEXT, estado TEXT NOT NULL, ausente_na_origem INTEGER NOT NULL DEFAULT 0,
  primeiro_erro TEXT, ultimo_erro TEXT, codigo_excecao TEXT, tentativas INTEGER NOT NULL DEFAULT 0,
  atualizado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_itens_proc ON itens(protocolo);
CREATE TABLE IF NOT EXISTS versoes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, chave TEXT NOT NULL REFERENCES itens(chave),
  versao INTEGER NOT NULL, sha256 TEXT NOT NULL, tamanho INTEGER NOT NULL,
  caminho_relativo TEXT NOT NULL, execucao_id INTEGER, confirmado_em TEXT NOT NULL, impressao TEXT,
  UNIQUE(chave, versao), UNIQUE(chave, sha256)
);
CREATE TABLE IF NOT EXISTS eventos (
  id INTEGER PRIMARY KEY AUTOINCREMENT, em TEXT NOT NULL, execucao_id INTEGER,
  protocolo TEXT, chave TEXT, de TEXT, para TEXT NOT NULL, codigo TEXT, motivo TEXT
);
"""


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Estado:
    def __init__(self, caminho: str | Path):
        self.caminho = str(caminho)
        Path(self.caminho).parent.mkdir(parents=True, exist_ok=True) if self.caminho != ":memory:" else None
        self.db = sqlite3.connect(self.caminho, isolation_level=None, timeout=60)   # vários robôs (fatias)
        self.db.execute("PRAGMA busy_timeout=60000")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        for tabela in ("itens", "processos"):                       # migração: coluna de evidência (print)
            cols = {r[1] for r in self.db.execute(f"PRAGMA table_info({tabela})")}
            if "evidencia" not in cols:
                self.db.execute(f"ALTER TABLE {tabela} ADD COLUMN evidencia TEXT")

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def backup(self, destino: str | Path) -> None:
        with sqlite3.connect(str(destino)) as alvo:
            self.db.backup(alvo)

    # --- execuções ----------------------------------------------------------
    def iniciar_execucao(self, modo: str, filtros: str) -> int:
        cur = self.db.execute("INSERT INTO execucoes(modo, filtros, inicio, status) VALUES (?,?,?,?)",
                              (modo, filtros, agora(), "em_andamento"))
        return int(cur.lastrowid)

    def encerrar_execucao(self, exec_id: int, status: str, resumo: dict[str, Any]) -> None:
        self.db.execute("UPDATE execucoes SET fim=?, status=?, resumo=? WHERE id=?",
                        (agora(), status, json.dumps(resumo, ensure_ascii=False), exec_id))

    def registrar_pagina(self, exec_id: int, pagina: int, cursor: Optional[str], total: Optional[int],
                         protocolos: list[str], anomalia: Optional[str]) -> None:
        self.db.execute("INSERT INTO descoberta_paginas(execucao_id,pagina,cursor,total_exibido,protocolos,anomalia,"
                        "registrado_em) VALUES (?,?,?,?,?,?,?)",
                        (exec_id, pagina, cursor, total, json.dumps(protocolos), anomalia, agora()))

    # --- processos ----------------------------------------------------------
    def registrar_processo(self, protocolo: str, id_interno: Optional[str], exec_id: Optional[int]) -> bool:
        """Retorna True se for novo."""
        with self.tx() as db:
            row = db.execute("SELECT 1 FROM processos WHERE protocolo=?", (protocolo,)).fetchone()
            if row:
                if id_interno:
                    db.execute("UPDATE processos SET id_interno=COALESCE(id_interno, ?) WHERE protocolo=?",
                               (id_interno, protocolo))
                return False
            db.execute("INSERT INTO processos(protocolo,id_interno,estado,descoberto_em,atualizado_em) "
                       "VALUES (?,?,?,?,?)", (protocolo, id_interno, EstadoProcesso.DESCOBERTO.value, agora(), agora()))
            db.execute("INSERT INTO eventos(em,execucao_id,protocolo,para) VALUES (?,?,?,?)",
                       (agora(), exec_id, protocolo, EstadoProcesso.DESCOBERTO.value))
            return True

    def renomear_processo(self, antigo: str, novo: str, exec_id: Optional[int]) -> bool:
        """Troca a chave de um processo ainda não iniciado (descoberto) para a chave composta."""
        with self.tx() as db:
            row = db.execute("SELECT estado FROM processos WHERE protocolo=?", (antigo,)).fetchone()
            if not row or row["estado"] != "descoberto" or \
               db.execute("SELECT 1 FROM itens WHERE protocolo=?", (antigo,)).fetchone():
                return False
            if db.execute("SELECT 1 FROM processos WHERE protocolo=?", (novo,)).fetchone():
                db.execute("DELETE FROM processos WHERE protocolo=?", (antigo,))
            else:
                db.execute("UPDATE processos SET protocolo=? WHERE protocolo=?", (novo, antigo))
            db.execute("UPDATE eventos SET protocolo=? WHERE protocolo=?", (novo, antigo))
            db.execute("INSERT INTO eventos(em,execucao_id,protocolo,de,para,motivo) VALUES (?,?,?,?,?,?)",
                       (agora(), exec_id, novo, antigo, "descoberto", "chave composta: número repetido/ausente no SIGA"))
            return True

    def processo(self, protocolo: str) -> Optional[sqlite3.Row]:
        return self.db.execute("SELECT * FROM processos WHERE protocolo=?", (protocolo,)).fetchone()

    def processos(self, estados: Optional[list[EstadoProcesso]] = None) -> list[sqlite3.Row]:
        if estados:
            marks = ",".join("?" * len(estados))
            return self.db.execute(f"SELECT * FROM processos WHERE estado IN ({marks}) ORDER BY protocolo",
                                   [e.value for e in estados]).fetchall()
        return self.db.execute("SELECT * FROM processos ORDER BY protocolo").fetchall()

    def mudar_processo(self, protocolo: str, para: EstadoProcesso, exec_id: Optional[int],
                       codigo: Optional[str] = None, motivo: Optional[str] = None,
                       listagem_completa: Optional[bool] = None) -> None:
        with self.tx() as db:
            row = db.execute("SELECT estado, primeiro_erro FROM processos WHERE protocolo=?", (protocolo,)).fetchone()
            de = row["estado"] if row else None
            erro = bool(codigo)
            db.execute(
                "UPDATE processos SET estado=?, ultima_execucao=?, atualizado_em=?, codigo_excecao=?,"
                " ultimo_erro=CASE WHEN ? THEN ? ELSE ultimo_erro END,"
                " primeiro_erro=CASE WHEN ? AND primeiro_erro IS NULL THEN ? ELSE primeiro_erro END,"
                " tentativas=tentativas + CASE WHEN ? THEN 1 ELSE 0 END,"
                " listagem_completa=COALESCE(?, listagem_completa) WHERE protocolo=?",
                (para.value, exec_id, agora(), codigo, erro, motivo, erro, motivo, erro,
                 None if listagem_completa is None else int(listagem_completa), protocolo))
            db.execute("INSERT INTO eventos(em,execucao_id,protocolo,de,para,codigo,motivo) VALUES (?,?,?,?,?,?,?)",
                       (agora(), exec_id, protocolo, de, para.value, codigo, motivo))

    def salvar_identificacao(self, protocolo: str, identificacao: dict[str, Any]) -> None:
        self.db.execute("UPDATE processos SET identificacao=?, atualizado_em=? WHERE protocolo=?",
                        (json.dumps(identificacao, ensure_ascii=False), agora(), protocolo))

    def reservar_pasta(self, protocolo: str, pasta: str) -> Optional[str]:
        """Reserva a pasta para o protocolo. Retorna o protocolo conflitante, se houver (EX-04)."""
        with self.tx() as db:
            row = db.execute("SELECT protocolo FROM pastas WHERE pasta=?", (pasta,)).fetchone()
            if row and row["protocolo"] != protocolo:
                return row["protocolo"]
            atual = db.execute("SELECT pasta FROM processos WHERE protocolo=?", (protocolo,)).fetchone()
            if atual and atual["pasta"] and atual["pasta"] != pasta:
                return f"(pasta anterior {atual['pasta']})"
            db.execute("INSERT OR IGNORE INTO pastas(pasta, protocolo) VALUES (?,?)", (pasta, protocolo))
            db.execute("UPDATE processos SET pasta=? WHERE protocolo=?", (pasta, protocolo))
            return None

    # --- itens --------------------------------------------------------------
    def registrar_item(self, chave: str, protocolo: str, tipo: str, *, id_origem=None, nome_original=None,
                       contexto=None, ordinal=None, tamanho=None, data=None, exec_id=None) -> bool:
        with self.tx() as db:
            row = db.execute("SELECT estado FROM itens WHERE chave=?", (chave,)).fetchone()
            if row:
                db.execute("UPDATE itens SET ausente_na_origem=0, tamanho_origem=COALESCE(?, tamanho_origem),"
                           " data_origem=COALESCE(?, data_origem) WHERE chave=?", (tamanho, data, chave))
                return False
            db.execute("INSERT INTO itens(chave,protocolo,tipo,id_origem,nome_original,contexto,ordinal,tamanho_origem,"
                       "data_origem,estado,atualizado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (chave, protocolo, tipo, id_origem, nome_original, contexto, ordinal, tamanho, data,
                        EstadoItem.DESCOBERTO.value, agora()))
            db.execute("INSERT INTO eventos(em,execucao_id,protocolo,chave,para) VALUES (?,?,?,?,?)",
                       (agora(), exec_id, protocolo, chave, EstadoItem.DESCOBERTO.value))
            return True

    def item(self, chave: str) -> Optional[sqlite3.Row]:
        return self.db.execute("SELECT * FROM itens WHERE chave=?", (chave,)).fetchone()

    def itens(self, protocolo: Optional[str] = None) -> list[sqlite3.Row]:
        if protocolo:
            return self.db.execute("SELECT * FROM itens WHERE protocolo=? ORDER BY tipo, contexto, ordinal",
                                   (protocolo,)).fetchall()
        return self.db.execute("SELECT * FROM itens ORDER BY protocolo, tipo, contexto, ordinal").fetchall()

    def marcar_ausentes(self, protocolo: str, chaves_presentes: set[str]) -> list[str]:
        """Itens já inventariados que não aparecem mais na origem: registra, não apaga (auditoria)."""
        ausentes = [r["chave"] for r in self.itens(protocolo)
                    if r["tipo"] == "anexo" and r["chave"] not in chaves_presentes and not r["ausente_na_origem"]]
        for c in ausentes:
            self.db.execute("UPDATE itens SET ausente_na_origem=1, atualizado_em=? WHERE chave=?", (agora(), c))
        return ausentes

    def mudar_item(self, chave: str, para: EstadoItem, exec_id: Optional[int], codigo: Optional[str] = None,
                   motivo: Optional[str] = None) -> None:
        with self.tx() as db:
            row = db.execute("SELECT estado, protocolo FROM itens WHERE chave=?", (chave,)).fetchone()
            erro = bool(codigo)
            db.execute(
                "UPDATE itens SET estado=?, atualizado_em=?, codigo_excecao=?,"
                " ultimo_erro=CASE WHEN ? THEN ? ELSE ultimo_erro END,"
                " primeiro_erro=CASE WHEN ? AND primeiro_erro IS NULL THEN ? ELSE primeiro_erro END,"
                " tentativas=tentativas + CASE WHEN ? THEN 1 ELSE 0 END WHERE chave=?",
                (para.value, agora(), codigo, erro, motivo, erro, motivo, erro, chave))
            db.execute("INSERT INTO eventos(em,execucao_id,protocolo,chave,de,para,codigo,motivo) VALUES (?,?,?,?,?,?,?,?)",
                       (agora(), exec_id, row["protocolo"], chave, row["estado"], para.value, codigo, motivo))

    # --- versões ------------------------------------------------------------
    def versoes(self, chave: str) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM versoes WHERE chave=? ORDER BY versao", (chave,)).fetchall()

    def versao_por_hash(self, chave: str, sha: str) -> Optional[sqlite3.Row]:
        return self.db.execute("SELECT * FROM versoes WHERE chave=? AND sha256=?", (chave, sha)).fetchone()

    def versao_por_impressao(self, chave: str, impressao: str) -> Optional[sqlite3.Row]:
        return self.db.execute("SELECT * FROM versoes WHERE chave=? AND impressao=?", (chave, impressao)).fetchone()

    def proxima_versao(self, chave: str) -> int:
        row = self.db.execute("SELECT MAX(versao) m FROM versoes WHERE chave=?", (chave,)).fetchone()
        return (row["m"] or 0) + 1

    def confirmar_versao(self, chave: str, versao: int, sha: str, tamanho: int, rel: str, exec_id: Optional[int],
                         impressao: Optional[str] = None) -> None:
        """Grava versão e confirma o item na MESMA transação (só após a gravação final verificada)."""
        with self.tx() as db:
            db.execute("INSERT OR IGNORE INTO versoes(chave,versao,sha256,tamanho,caminho_relativo,execucao_id,confirmado_em,"
                       "impressao) VALUES (?,?,?,?,?,?,?,?)", (chave, versao, sha, tamanho, rel, exec_id, agora(), impressao))
            row = db.execute("SELECT estado, protocolo FROM itens WHERE chave=?", (chave,)).fetchone()
            db.execute("UPDATE itens SET estado=?, codigo_excecao=NULL, atualizado_em=? WHERE chave=?",
                       (EstadoItem.CONFIRMADO.value, agora(), chave))
            db.execute("INSERT INTO eventos(em,execucao_id,protocolo,chave,de,para,motivo) VALUES (?,?,?,?,?,?,?)",
                       (agora(), exec_id, row["protocolo"], chave, row["estado"], EstadoItem.CONFIRMADO.value,
                        f"v{versao} sha256={sha[:12]}"))

    def registrar_evidencia(self, tabela: str, chave: str, caminho: str) -> None:
        col = "chave" if tabela == "itens" else "protocolo"
        self.db.execute(f"UPDATE {tabela} SET evidencia=? WHERE {col}=?", (caminho, chave))

    def eventos(self, protocolo: Optional[str] = None) -> list[sqlite3.Row]:
        if protocolo:
            return self.db.execute("SELECT * FROM eventos WHERE protocolo=? ORDER BY id", (protocolo,)).fetchall()
        return self.db.execute("SELECT * FROM eventos ORDER BY id").fetchall()

    def contagens(self) -> dict[str, dict[str, int]]:
        p = {r["estado"]: r["n"] for r in self.db.execute("SELECT estado, COUNT(*) n FROM processos GROUP BY estado")}
        i = {r["estado"]: r["n"] for r in self.db.execute("SELECT estado, COUNT(*) n FROM itens GROUP BY estado")}
        v = self.db.execute("SELECT COUNT(*) n, COALESCE(SUM(tamanho),0) b FROM versoes").fetchone()
        return {"processos": p, "itens": i, "versoes": {"arquivos": v["n"], "bytes": v["b"]}}
