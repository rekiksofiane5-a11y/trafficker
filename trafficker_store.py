# -*- coding: utf-8 -*-
"""Persistance SQLite de l'état de l'UI : jobs, plans analysés, échecs de login.

Tout l'état partagé vit ici, pas en mémoire : plusieurs processus (gunicorn -w N)
ou un redémarrage voient les mêmes jobs, jetons d'analyse et compteurs anti-force
brute. Condition : une seule base partagée (même machine ou même volume).

RGPD : aucune clé ni secret n'est stocké (clé de compte de service, secret Adform
sont renvoyés par le navigateur à chaque action). Rétention limitée : `purge()`.
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
CREATE TABLE IF NOT EXISTS plans (
    token TEXT PRIMARY KEY,
    created REAL NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS login_failures (
    ip TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS login_failures_ip ON login_failures (ip, ts);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    created REAL NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    log TEXT NOT NULL DEFAULT '[]',
    report TEXT,
    delivery TEXT
);
"""
_ready: set = set()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=15)
    if DB_PATH not in _ready:
        c.execute("PRAGMA journal_mode=WAL")   # lectures et écritures concurrentes
        c.executescript(_SCHEMA)
        _ready.add(DB_PATH)
    return c


# ---------------------------------------------------------------------------
# Plans analysés (jetons) — sérialisés en JSON, sans secret
# ---------------------------------------------------------------------------

PLAN_SAFE_KEYS = ("platform", "profile_id", "creatives_dir", "rows", "demo", "created")


def _plan_to_json(plan) -> list:
    from dataclasses import asdict
    out = []
    for camp in plan.values():
        d = asdict(camp)
        out.append(d)
    return out


def _plan_from_json(items) -> dict:
    from cm360_trafficker import CampaignSpec, CreativeSpec, PlacementSpec
    plan = {}
    for d in items:
        placements = {k: PlacementSpec(**v) for k, v in d.pop("placements").items()}
        ads = {}
        for name, ad in d.pop("ads").items():
            ad = dict(ad)
            ad["creatives"] = [CreativeSpec(**c) for c in ad["creatives"]]
            ads[name] = ad
        camp = CampaignSpec(**d, placements=placements, ads=ads)
        plan[f"{(str(camp.advertiser_id or '') or camp.advertiser_name).lower()}|{camp.name.lower()}"] = camp
    return plan


def save_plan(token: str, job: dict) -> None:
    """Enregistre un plan analysé. Les identifiants (clé SA, secret Adform) ne sont
    jamais écrits : seuls PLAN_SAFE_KEYS + le plan sérialisé."""
    data = {k: job.get(k) for k in PLAN_SAFE_KEYS}
    data["rows"] = list(data.get("rows") or [])
    data["plan"] = _plan_to_json(job["plan"])
    with _lock, _conn() as c:
        c.execute("INSERT OR REPLACE INTO plans (token, created, data) VALUES (?, ?, ?)",
                  (token, job.get("created", time.time()), json.dumps(data, ensure_ascii=False)))


def _decode_plan(raw: str) -> dict:
    data = json.loads(raw)
    data["plan"] = _plan_from_json(data["plan"])
    return data


def load_plan(token: str, max_age: Optional[int] = None) -> Optional[dict]:
    oldest = time.time() - max_age if max_age is not None else 0
    with _lock, _conn() as c:
        r = c.execute("SELECT data FROM plans WHERE token = ? AND created >= ?",
                      (token, oldest)).fetchone()
    return _decode_plan(r[0]) if r else None


def take_plan(token: str, max_age: Optional[int] = None) -> Optional[dict]:
    """Retire et renvoie un plan : un seul processus peut le prendre (un plan ne
    peut être lancé qu'une fois, même si deux requêtes arrivent ensemble)."""
    oldest = time.time() - max_age if max_age is not None else 0
    with _lock, _conn() as c:
        r = c.execute("SELECT data FROM plans WHERE token = ? AND created >= ?",
                      (token, oldest)).fetchone()
        if not r:
            return None
        if c.execute("DELETE FROM plans WHERE token = ?", (token,)).rowcount != 1:
            return None   # pris entre-temps par un autre processus
    return _decode_plan(r[0])


# ---------------------------------------------------------------------------
# Échecs de connexion (anti-force brute partagé entre processus)
# ---------------------------------------------------------------------------

def login_failures(ip: str, window: int) -> int:
    with _lock, _conn() as c:
        return c.execute("SELECT COUNT(*) FROM login_failures WHERE ip = ? AND ts >= ?",
                         (ip, time.time() - window)).fetchone()[0]


def add_login_failure(ip: str) -> None:
    with _lock, _conn() as c:
        c.execute("INSERT INTO login_failures (ip, ts) VALUES (?, ?)", (ip, time.time()))


def clear_login_failures(ip: Optional[str] = None) -> None:
    with _lock, _conn() as c:
        if ip is None:
            c.execute("DELETE FROM login_failures")
        else:
            c.execute("DELETE FROM login_failures WHERE ip = ?", (ip,))


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


def load_job(job_id: str, max_age: Optional[int] = None) -> Optional[dict]:
    """Charge un job ; avec `max_age`, un job plus ancien est ignoré (rétention)."""
    oldest = time.time() - max_age if max_age is not None else 0
    with _lock, _conn() as c:
        r = c.execute("SELECT label, created, done, error, log, report, delivery"
                      " FROM jobs WHERE id = ? AND created >= ?", (job_id, oldest)).fetchone()
    if not r:
        return None
    return {"label": r[0], "created": r[1], "done": bool(r[2]), "error": r[3],
            "log": json.loads(r[4]), "report": json.loads(r[5]) if r[5] else None,
            "delivery": json.loads(r[6]) if r[6] else {}}


def list_jobs(limit: int = 20, max_age: Optional[int] = None) -> List[Dict]:
    oldest = time.time() - max_age if max_age is not None else 0
    with _lock, _conn() as c:
        rows = c.execute("SELECT id, label, done, error FROM jobs WHERE created >= ?"
                         " ORDER BY created DESC LIMIT ?", (oldest, limit)).fetchall()
    return [{"id": r[0], "label": r[1], "done": bool(r[2]), "error": bool(r[3])}
            for r in rows]


def purge(max_age_seconds: int, login_window: int = 3600) -> List[str]:
    """RGPD : supprime jobs et plans plus vieux que `max_age_seconds`, et les
    échecs de login hors fenêtre. Renvoie les dossiers de créatives des plans
    supprimés (à effacer du disque par l'appelant)."""
    limit = time.time() - max_age_seconds
    with _lock, _conn() as c:
        dirs = [json.loads(r[0]).get("creatives_dir") or ""
                for r in c.execute("SELECT data FROM plans WHERE created < ?", (limit,))]
        c.execute("DELETE FROM plans WHERE created < ?", (limit,))
        c.execute("DELETE FROM jobs WHERE created < ?", (limit,))
        c.execute("DELETE FROM login_failures WHERE ts < ?", (time.time() - login_window,))
    return [d for d in dirs if d]
