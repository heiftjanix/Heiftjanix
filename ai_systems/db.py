"""SQLite-Store für die virtuelle Firma: Abteilungen, Agenten („Mitarbeiter"),
Konnektor-Freigaben, Netzwerkregeln und Chat-Verläufe.

Secrets landen NIE in dieser Datenbank — Zugangsdaten bleiben ausschließlich in
Umgebungsvariablen (siehe connectors.py). Alle Funktionen nehmen eine offene
Connection entgegen, damit Tests mit ":memory:" arbeiten können.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import config

_LOCK = threading.Lock()
_CONN: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS departments (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  icon TEXT NOT NULL DEFAULT '🏢',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agents (
  id INTEGER PRIMARY KEY,
  department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  n8n_workflow_id TEXT,
  active INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS department_connectors (
  department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
  connector_key TEXT NOT NULL,
  PRIMARY KEY (department_id, connector_key)
);
CREATE TABLE IF NOT EXISTS network_rules (
  id INTEGER PRIMARY KEY,
  department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
  agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
  pattern TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS chat_sessions (
  id INTEGER PRIMARY KEY,
  department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
  agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
  id INTEGER PRIMARY KEY,
  session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  proposal_json TEXT,
  agent_name TEXT,
  agent_role TEXT,
  created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def open_db(path: str | None = None) -> sqlite3.Connection:
    """Öffnet (und initialisiert) eine Datenbank; ':memory:' für Tests."""
    target = path or config.db_path()
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def get_conn() -> sqlite3.Connection:
    """Prozessweite Standard-Connection (die App ist Single-Prozess)."""
    global _CONN
    with _LOCK:
        if _CONN is None:
            _CONN = open_db()
        return _CONN


def reset_conn() -> None:
    """Nur für Tests: Standard-Connection verwerfen (z. B. nach ENV-Wechsel)."""
    global _CONN
    with _LOCK:
        if _CONN is not None:
            _CONN.close()
            _CONN = None


# --- Abteilungen -----------------------------------------------------------

def list_departments(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT d.*, (SELECT COUNT(*) FROM agents a WHERE a.department_id = d.id) AS agent_count
           FROM departments d ORDER BY d.name"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_department(conn: sqlite3.Connection, dep_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM departments WHERE id = ?", (dep_id,)).fetchone()
    return dict(row) if row else None


def create_department(conn: sqlite3.Connection, name: str, description: str = "",
                      icon: str = "🏢") -> dict:
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO departments (name, description, icon, created_at) VALUES (?, ?, ?, ?)",
            (name.strip(), description.strip(), icon.strip() or "🏢", _now()),
        )
        conn.commit()
    return get_department(conn, cur.lastrowid)  # type: ignore[return-value]


def update_department(conn: sqlite3.Connection, dep_id: int, **fields) -> dict | None:
    allowed = {k: v for k, v in fields.items() if k in ("name", "description", "icon") and v is not None}
    if allowed:
        sets = ", ".join(f"{k} = ?" for k in allowed)
        with _LOCK:
            conn.execute(f"UPDATE departments SET {sets} WHERE id = ?", (*allowed.values(), dep_id))
            conn.commit()
    return get_department(conn, dep_id)


def delete_department(conn: sqlite3.Connection, dep_id: int) -> None:
    with _LOCK:
        conn.execute("DELETE FROM departments WHERE id = ?", (dep_id,))
        conn.commit()


# --- Konnektor-Freigaben ---------------------------------------------------

def allowed_connectors(conn: sqlite3.Connection, dep_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT connector_key FROM department_connectors WHERE department_id = ? ORDER BY connector_key",
        (dep_id,),
    ).fetchall()
    return [r["connector_key"] for r in rows]


def set_allowed_connectors(conn: sqlite3.Connection, dep_id: int, keys: list[str]) -> None:
    with _LOCK:
        conn.execute("DELETE FROM department_connectors WHERE department_id = ?", (dep_id,))
        conn.executemany(
            "INSERT INTO department_connectors (department_id, connector_key) VALUES (?, ?)",
            [(dep_id, k) for k in sorted(set(keys))],
        )
        conn.commit()


# --- Agenten ---------------------------------------------------------------

def list_agents(conn: sqlite3.Connection, department_id: int | None = None) -> list[dict]:
    if department_id is None:
        rows = conn.execute("SELECT * FROM agents ORDER BY name").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM agents WHERE department_id = ? ORDER BY name", (department_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_agent(conn: sqlite3.Connection, agent_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
    return dict(row) if row else None


def create_agent(conn: sqlite3.Connection, department_id: int, name: str, role: str = "",
                 description: str = "", n8n_workflow_id: str | None = None) -> dict:
    now = _now()
    with _LOCK:
        cur = conn.execute(
            """INSERT INTO agents (department_id, name, role, description, n8n_workflow_id,
                                   created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (department_id, name.strip(), role.strip(), description.strip(), n8n_workflow_id, now, now),
        )
        conn.commit()
    return get_agent(conn, cur.lastrowid)  # type: ignore[return-value]


def update_agent(conn: sqlite3.Connection, agent_id: int, **fields) -> dict | None:
    allowed = {k: v for k, v in fields.items()
               if k in ("name", "role", "description", "n8n_workflow_id", "active") and v is not None}
    if allowed:
        sets = ", ".join(f"{k} = ?" for k in allowed)
        with _LOCK:
            conn.execute(
                f"UPDATE agents SET {sets}, updated_at = ? WHERE id = ?",
                (*allowed.values(), _now(), agent_id),
            )
            conn.commit()
    return get_agent(conn, agent_id)


def delete_agent(conn: sqlite3.Connection, agent_id: int) -> None:
    with _LOCK:
        conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        conn.commit()


# --- Netzwerkregeln --------------------------------------------------------

def list_rules(conn: sqlite3.Connection, dep_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM network_rules WHERE department_id = ? ORDER BY pattern", (dep_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def add_rule(conn: sqlite3.Connection, dep_id: int, pattern: str, note: str = "",
             agent_id: int | None = None) -> dict:
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO network_rules (department_id, agent_id, pattern, note) VALUES (?, ?, ?, ?)",
            (dep_id, agent_id, pattern.strip().lower(), note.strip()),
        )
        conn.commit()
    row = conn.execute("SELECT * FROM network_rules WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def delete_rule(conn: sqlite3.Connection, rule_id: int) -> None:
    with _LOCK:
        conn.execute("DELETE FROM network_rules WHERE id = ?", (rule_id,))
        conn.commit()


def effective_rule_patterns(conn: sqlite3.Connection, dep_id: int,
                            agent_id: int | None = None) -> list[str]:
    """Abteilungsweite Regeln plus (optional) agentenspezifische Regeln."""
    rows = conn.execute(
        """SELECT pattern FROM network_rules
           WHERE department_id = ? AND (agent_id IS NULL OR agent_id = ?)
           ORDER BY pattern""",
        (dep_id, agent_id),
    ).fetchall()
    return sorted({r["pattern"] for r in rows})


# --- Chat ------------------------------------------------------------------

def create_chat_session(conn: sqlite3.Connection, department_id: int,
                        agent_id: int | None = None) -> dict:
    with _LOCK:
        cur = conn.execute(
            "INSERT INTO chat_sessions (department_id, agent_id, created_at) VALUES (?, ?, ?)",
            (department_id, agent_id, _now()),
        )
        conn.commit()
    return get_chat_session(conn, cur.lastrowid)  # type: ignore[return-value]


def get_chat_session(conn: sqlite3.Connection, session_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def list_chat_messages(conn: sqlite3.Connection, session_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY id", (session_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def add_chat_message(conn: sqlite3.Connection, session_id: int, role: str, content: str,
                     proposal_json: str | None = None, agent_name: str | None = None,
                     agent_role: str | None = None) -> dict:
    with _LOCK:
        cur = conn.execute(
            """INSERT INTO chat_messages (session_id, role, content, proposal_json,
                                          agent_name, agent_role, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, role, content, proposal_json, agent_name, agent_role, _now()),
        )
        conn.commit()
    row = conn.execute("SELECT * FROM chat_messages WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def latest_proposal(conn: sqlite3.Connection, session_id: int) -> dict | None:
    """Jüngste Assistant-Nachricht mit Workflow-Vorschlag (für den Deploy-Schritt)."""
    row = conn.execute(
        """SELECT * FROM chat_messages
           WHERE session_id = ? AND role = 'assistant' AND proposal_json IS NOT NULL
           ORDER BY id DESC LIMIT 1""",
        (session_id,),
    ).fetchone()
    return dict(row) if row else None
