"""Encrypted durable session state for the local HTTP service."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

class SessionConflict(Exception):
    """An existing conversation ID belongs to a different authenticated context."""

class SessionStore:
    def __init__(self, path=None, key=None):
        self.path=Path(path or os.environ.get("SESSION_DB_PATH", ".local/sessions.sqlite3"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        key=key or os.environ.get("SESSION_ENCRYPTION_KEY")
        if not key:
            raise RuntimeError("SESSION_ENCRYPTION_KEY is required for durable HTTP sessions")
        try:
            self.fernet=Fernet(key.encode() if isinstance(key,str) else key)
        except (ValueError, TypeError) as exc:
            raise RuntimeError("SESSION_ENCRYPTION_KEY must be a Fernet key") from exc
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS conversations (conversation_id TEXT PRIMARY KEY, encrypted_payload BLOB NOT NULL, updated_at TEXT NOT NULL)")

    @contextmanager
    def _connect(self):
        db=sqlite3.connect(self.path, timeout=10, isolation_level="IMMEDIATE")
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def load(self, conversation_id):
        with self._connect() as db:
            row=db.execute("SELECT encrypted_payload FROM conversations WHERE conversation_id=?",(conversation_id,)).fetchone()
        if row is None: return None
        try:
            return json.loads(self.fernet.decrypt(row[0]).decode("utf-8"))
        except (InvalidToken, ValueError) as exc:
            raise RuntimeError("Stored conversation state could not be decrypted") from exc

    def save(self, conversation_id, payload):
        ciphertext=self.fernet.encrypt(json.dumps(payload,separators=(",",":"),ensure_ascii=False).encode("utf-8"))
        with self._connect() as db:
            db.execute("INSERT INTO conversations(conversation_id,encrypted_payload,updated_at) VALUES(?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET encrypted_payload=excluded.encrypted_payload,updated_at=excluded.updated_at",(conversation_id,ciphertext,datetime.now(timezone.utc).isoformat()))

    def delete(self, conversation_id):
        with self._connect() as db:
            db.execute("DELETE FROM conversations WHERE conversation_id=?",(conversation_id,))
