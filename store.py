"""
Couche de persistance du back-office (SQLite).

Remplace le dict statique clients.py et les constantes admin-éditables de
legal_rag/config.py comme source de vérité — tout est modifiable à chaud
depuis /admin sans redémarrer le serveur.

Une connexion SQLite est ouverte puis fermée à chaque appel (pas de connexion
partagée entre threads) : usage admin à faible concurrence, on s'appuie sur le
verrouillage fichier natif de SQLite.
"""
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "admin.db")

DEFAULT_SETTINGS = {
    "generation_backend": "mistral_api",   # "mistral_api" | "ollama_local"
    "generation_model": "mistral-small-latest",
    "pdf_mode": "docling",
    "web_mode": "mixed",                   # "separate" | "mixed"
    "max_distance": 0.9,
    "web_fallback_threshold": 0.6,
    "n_results": 12,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Crée les tables si absentes, puis seed depuis clients.py/config.py si vide (one-shot)."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                generation_backend TEXT NOT NULL,
                generation_model TEXT NOT NULL,
                pdf_mode TEXT NOT NULL,
                web_mode TEXT NOT NULL,
                max_distance REAL NOT NULL,
                web_fallback_threshold REAL NOT NULL,
                n_results INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                corpus_dir TEXT NOT NULL,
                collection TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS client_urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_key TEXT NOT NULL REFERENCES clients(key) ON DELETE CASCADE,
                url TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(client_key, url)
            )
        """)
        conn.commit()

    _seed_if_empty()


def _seed_if_empty():
    """Migration one-shot : importe clients.py (CLIENTS + LOCAL) si la table clients est vide."""
    with _connect() as conn:
        has_settings = conn.execute("SELECT 1 FROM settings WHERE id = 1").fetchone()
        has_clients = conn.execute("SELECT 1 FROM clients LIMIT 1").fetchone()

    if not has_settings:
        update_settings(**DEFAULT_SETTINGS)

    if not has_clients:
        try:
            from clients import CLIENTS, LOCAL
        except ImportError:
            return
        create_client_row("local", LOCAL["name"] if "name" in LOCAL else "Local",
                           LOCAL["corpus"], LOCAL["collection"], LOCAL.get("web_sources", []))
        for key, cfg in CLIENTS.items():
            create_client_row(key, cfg["name"], cfg["corpus"], cfg["collection"],
                               cfg.get("web_sources", []))
        print(f"✅ store.py : {1 + len(CLIENTS)} client(s) importé(s) depuis clients.py")


# ── Settings ──────────────────────────────────────────────────────────────
def get_settings() -> dict:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        if row is None:
            return dict(DEFAULT_SETTINGS)
        d = dict(row)
        d.pop("id", None)
        d.pop("updated_at", None)
        return d


def update_settings(**kwargs):
    current = get_settings()
    current.update({k: v for k, v in kwargs.items() if k in DEFAULT_SETTINGS})
    with _connect() as conn:
        conn.execute("""
            INSERT INTO settings (id, generation_backend, generation_model, pdf_mode,
                                   web_mode, max_distance, web_fallback_threshold,
                                   n_results, updated_at)
            VALUES (1, :generation_backend, :generation_model, :pdf_mode, :web_mode,
                    :max_distance, :web_fallback_threshold, :n_results, :updated_at)
            ON CONFLICT(id) DO UPDATE SET
                generation_backend=excluded.generation_backend,
                generation_model=excluded.generation_model,
                pdf_mode=excluded.pdf_mode,
                web_mode=excluded.web_mode,
                max_distance=excluded.max_distance,
                web_fallback_threshold=excluded.web_fallback_threshold,
                n_results=excluded.n_results,
                updated_at=excluded.updated_at
        """, {**current, "updated_at": _now()})
        conn.commit()


# ── Clients ───────────────────────────────────────────────────────────────
def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "client"


def list_clients() -> list:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM clients ORDER BY (key = 'local') DESC, created_at").fetchall()
        return [dict(r) for r in rows]


def get_client(key: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM clients WHERE key = ?", (key,)).fetchone()
        return dict(row) if row else None


def create_client_row(key: str, name: str, corpus_dir: str, collection: str,
                       web_sources: Optional[list] = None) -> dict:
    """Insertion bas niveau — utilisée par le seed initial ET create_client()."""
    Path(corpus_dir).mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute("""
            INSERT INTO clients (key, name, corpus_dir, collection, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(key) DO NOTHING
        """, (key, name, corpus_dir, collection, _now()))
        conn.commit()
    for url in (web_sources or []):
        add_url(key, url)
    return get_client(key)


def create_client(name: str) -> dict:
    """Crée un nouveau client depuis le back-office : génère key/corpus_dir/collection."""
    slug = _slugify(name)
    key = f"sk-{slug}-{secrets.token_hex(4)}"
    corpus_dir = f"./documents/{slug}"
    collection = f"corpus_{slug.replace('-', '_')}"
    return create_client_row(key, name, corpus_dir, collection)


def update_client(key: str, **kwargs):
    fields = {k: v for k, v in kwargs.items() if k in ("name", "corpus_dir", "collection")}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    with _connect() as conn:
        conn.execute(f"UPDATE clients SET {set_clause} WHERE key = :key",
                     {**fields, "key": key})
        conn.commit()


def delete_client(key: str):
    """Supprime uniquement l'entrée DB (+ ses URLs, via ON DELETE CASCADE).
    Ne touche jamais aux fichiers du corpus ni à la collection ChromaDB —
    ce nettoyage physique, destructif, est géré explicitement par l'appelant
    (admin_routes.py) via des cases à cocher dédiées."""
    with _connect() as conn:
        conn.execute("DELETE FROM clients WHERE key = ?", (key,))
        conn.commit()


# ── URLs ──────────────────────────────────────────────────────────────────
def list_urls(client_key: str) -> list:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, url FROM client_urls WHERE client_key = ? ORDER BY created_at",
            (client_key,)
        ).fetchall()
        return [dict(r) for r in rows]


def list_url_strings(client_key: str) -> list:
    return [r["url"] for r in list_urls(client_key)]


def add_url(client_key: str, url: str):
    url = url.strip().rstrip("/")
    if not url:
        return
    with _connect() as conn:
        conn.execute("""
            INSERT INTO client_urls (client_key, url, created_at) VALUES (?, ?, ?)
            ON CONFLICT(client_key, url) DO NOTHING
        """, (client_key, url, _now()))
        conn.commit()


def remove_url(url_id: int):
    with _connect() as conn:
        conn.execute("DELETE FROM client_urls WHERE id = ?", (url_id,))
        conn.commit()
