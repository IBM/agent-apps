"""Credentials vault — phase 3 v1 skeleton.

Stores per-tool secrets in SQLite. NOT real encryption — base64 + a
process-local key derived from a salt. Good enough for a local dev demo
and a clear interface, NOT for production. Phase 3.5 will wire this to
the OS keyring (keyring package on macOS / Linux secret-service).
"""

from __future__ import annotations

import base64
import logging
import os
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "vault.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS secrets (
    tool_id     TEXT NOT NULL,
    secret_key  TEXT NOT NULL,
    value_b64   TEXT NOT NULL,
    PRIMARY KEY (tool_id, secret_key)
);
"""


class Vault:
    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        # Trivial obfuscation. Replace with OS keyring in phase 3.5.
        self._key = (os.environ.get("VAULT_KEY") or "chief-of-staff-vault").encode()

    def put(self, tool_id: str, secret_key: str, value: str) -> None:
        encoded = base64.b64encode(self._xor(value.encode())).decode()
        self._conn.execute(
            """
            INSERT INTO secrets (tool_id, secret_key, value_b64) VALUES (?, ?, ?)
            ON CONFLICT(tool_id, secret_key) DO UPDATE SET value_b64 = excluded.value_b64
            """,
            (tool_id, secret_key, encoded),
        )
        self._conn.commit()

    def get(self, tool_id: str, secret_key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value_b64 FROM secrets WHERE tool_id = ? AND secret_key = ?",
            (tool_id, secret_key),
        ).fetchone()
        if row is None:
            return None
        return self._xor(base64.b64decode(row["value_b64"])).decode()

    def has_all(self, tool_id: str, required: list[str]) -> bool:
        if not required:
            return True
        rows = self._conn.execute(
            f"SELECT secret_key FROM secrets WHERE tool_id = ? AND secret_key IN ({','.join(['?'] * len(required))})",
            (tool_id, *required),
        ).fetchall()
        return len(rows) == len(required)

    def delete(self, tool_id: str, secret_key: str | None = None) -> None:
        if secret_key is None:
            self._conn.execute("DELETE FROM secrets WHERE tool_id = ?", (tool_id,))
        else:
            self._conn.execute(
                "DELETE FROM secrets WHERE tool_id = ? AND secret_key = ?",
                (tool_id, secret_key),
            )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _xor(self, data: bytes) -> bytes:
        out = bytearray(len(data))
        klen = len(self._key)
        for i, b in enumerate(data):
            out[i] = b ^ self._key[i % klen]
        return bytes(out)
