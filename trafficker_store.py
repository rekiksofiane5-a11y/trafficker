# -*- coding: utf-8 -*-
"""Persistance SQLite des jobs de trafficking (survit au redémarrage de l'UI).

RGPD : aucune clé ni secret n'est stocké (clé de compte de service, secret
Adform restent en mémoire). Rétention limitée : les lignes plus anciennes que
`RETENTION_SECONDS` sont supprimées par `purge()`.
"""
import json
import os
import sqlite3
import threading
import time
from typing import Dict, List, Optional

DB_PATH = os.environ.get("TRAFFICKER_DB", "trafficker.db")
_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    created REAL NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    log TEXT NOT NULL DEFAULT '[]',
    report TEXT,
    delivery TEXT
)
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.execute(_SCHEMA)
    return c


def save_job(job_id: str, state: dict) -> None:
    """Enregistre (ou met à jour) l'état d'un job. `delivery` ne garde que
    les lignes du plan et la plateforme, jamais les identifiants."""
    d = state.get("delivery") or {}
    safe_delivery = {k: d.get(k) for k in ("rows", "platform", "profile_id", "demo")}
    with _lock, _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO jobs (id, label, created, done, error, log, report, delivery)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, state.get("label", "Trafficking"), state.get("created", time.time()),
             1 if state.get("done") else 0, state.get("error"),
             json.dumps(state.get("log", []), ensure_ascii=False),
             json.dumps(state["report"], ensure_ascii=False) if state.get("report") else None,
             json.dumps(safe_delivery, ensure_ascii=False) if safe_delivery.get("rows") else None))


def load_job(job_id: str) -> Optional[dict]:
    with _lock, _conn() as c:
        r = c.execute("SELECT label, created, done, error, log, report, delivery"
                      " FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not r:
        return None
    return {"label": r[0], "created": r[1], "done": bool(r[2]), "error": r[3],
            "log": json.loads(r[4]), "report": json.loads(r[5]) if r[5] else None,
            "delivery": json.loads(r[6]) if r[6] else {}}


def list_jobs(limit: int = 20) -> List[Dict]:
    with _lock, _conn() as c:
        rows = c.execute("SELECT id, label, done, error FROM jobs"
                         " ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
    return [{"id": r[0], "label": r[1], "done": bool(r[2]), "error": bool(r[3])}
            for r in rows]


def purge(max_age_seconds: int) -> int:
    """RGPD : supprime les jobs plus vieux que `max_age_seconds`."""
    with _lock, _conn() as c:
        cur = c.execute("DELETE FROM jobs WHERE created < ?",
                        (time.time() - max_age_seconds,))
        return cur.rowcount
