import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    first_seen INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS subscriptions (
    user_id INTEGER PRIMARY KEY,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    days INTEGER NOT NULL,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    paid_at INTEGER,
    UNIQUE (provider, external_id)
);
CREATE TABLE IF NOT EXISTS child_bots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL,
    token TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL,
    plugin TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
    scope TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (scope, key)
);
"""


@dataclass(frozen=True)
class ChildBot:
    id: int
    owner_id: int
    token: str
    username: str
    plugin: str
    active: bool


@dataclass(frozen=True)
class Payment:
    provider: str
    external_id: str
    user_id: int
    days: int
    amount: str
    currency: str
    status: str


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def _write(self, sql: str, params: tuple = ()) -> int:
        with self._conn:
            cur = self._conn.execute(sql, params)
            return cur.lastrowid or cur.rowcount

    def _one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self._conn.execute(sql, params).fetchone()

    def _all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self._conn.execute(sql, params).fetchall()

    # users and subscriptions

    def touch_user(self, user_id: int) -> None:
        self._write(
            "INSERT OR IGNORE INTO users (user_id, first_seen) VALUES (?, ?)",
            (user_id, int(time.time())),
        )

    def subscription_expires(self, user_id: int) -> int:
        row = self._one("SELECT expires_at FROM subscriptions WHERE user_id = ?", (user_id,))
        return row["expires_at"] if row else 0

    def revoke_subscription(self, user_id: int) -> None:
        self._write("UPDATE subscriptions SET expires_at = 0 WHERE user_id = ?", (user_id,))

    def extend_subscription(self, user_id: int, days: int) -> int:
        now = int(time.time())
        base = max(now, self.subscription_expires(user_id))
        expires = base + days * 86400
        self._write(
            "INSERT INTO subscriptions (user_id, expires_at) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET expires_at = excluded.expires_at",
            (user_id, expires),
        )
        return expires

    def stats(self) -> dict[str, int]:
        now = int(time.time())
        return {
            "users": self._one("SELECT COUNT(*) AS n FROM users")["n"],
            "active_subs": self._one(
                "SELECT COUNT(*) AS n FROM subscriptions WHERE expires_at > ?", (now,)
            )["n"],
            "child_bots": self._one(
                "SELECT COUNT(*) AS n FROM child_bots WHERE active = 1"
            )["n"],
            "paid_payments": self._one(
                "SELECT COUNT(*) AS n FROM payments WHERE status = 'paid'"
            )["n"],
        }

    # payments

    def create_pending_payment(
        self, provider: str, external_id: str, user_id: int, days: int, amount: str, currency: str
    ) -> None:
        self._write(
            "INSERT OR IGNORE INTO payments "
            "(provider, external_id, user_id, days, amount, currency, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (provider, external_id, user_id, days, amount, currency, int(time.time())),
        )

    def get_payment(self, provider: str, external_id: str) -> Payment | None:
        row = self._one(
            "SELECT * FROM payments WHERE provider = ? AND external_id = ?",
            (provider, external_id),
        )
        return _payment(row) if row else None

    def mark_payment_paid(self, provider: str, external_id: str) -> bool:
        """True только для перехода из pending/unknown в paid: защита от двойного зачисления."""
        cur = self._conn.execute(
            "UPDATE payments SET status = 'paid', paid_at = ? "
            "WHERE provider = ? AND external_id = ? AND status = 'pending'",
            (int(time.time()), provider, external_id),
        )
        self._conn.commit()
        return cur.rowcount == 1

    def insert_paid_payment(
        self, provider: str, external_id: str, user_id: int, days: int, amount: str, currency: str
    ) -> bool:
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO payments "
            "(provider, external_id, user_id, days, amount, currency, status, created_at, paid_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'paid', ?, ?)",
            (provider, external_id, user_id, days, amount, currency, int(time.time()), int(time.time())),
        )
        self._conn.commit()
        return cur.rowcount == 1

    def set_payment_status(self, provider: str, external_id: str, status: str) -> None:
        self._write(
            "UPDATE payments SET status = ? WHERE provider = ? AND external_id = ?",
            (status, provider, external_id),
        )

    def pending_payments(self, provider: str) -> list[Payment]:
        rows = self._all(
            "SELECT * FROM payments WHERE provider = ? AND status = 'pending'", (provider,)
        )
        return [_payment(r) for r in rows]

    # child bots

    def add_child_bot(self, owner_id: int, token: str, username: str, plugin: str) -> int:
        return self._write(
            "INSERT INTO child_bots (owner_id, token, username, plugin, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (owner_id, token, username, plugin, int(time.time())),
        )

    def child_bots_of(self, owner_id: int) -> list[ChildBot]:
        rows = self._all(
            "SELECT * FROM child_bots WHERE owner_id = ? AND active = 1 ORDER BY id", (owner_id,)
        )
        return [_child(r) for r in rows]

    def active_child_bots(self) -> list[ChildBot]:
        return [_child(r) for r in self._all("SELECT * FROM child_bots WHERE active = 1 ORDER BY id")]

    def find_child_bot(self, bot_id: int) -> ChildBot | None:
        row = self._one("SELECT * FROM child_bots WHERE id = ?", (bot_id,))
        return _child(row) if row else None

    def child_bot_by_token(self, token: str) -> ChildBot | None:
        row = self._one("SELECT * FROM child_bots WHERE token = ?", (token,))
        return _child(row) if row else None

    def deactivate_child_bot(self, bot_id: int) -> None:
        self._write("UPDATE child_bots SET active = 0 WHERE id = ?", (bot_id,))

    # generic per-scope storage used by plugins

    def kv_get(self, scope: str, key: str, default: Any = None) -> Any:
        row = self._one("SELECT value FROM kv WHERE scope = ? AND key = ?", (scope, key))
        return json.loads(row["value"]) if row else default

    def kv_set(self, scope: str, key: str, value: Any) -> None:
        self._write(
            "INSERT INTO kv (scope, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(scope, key) DO UPDATE SET value = excluded.value",
            (scope, key, json.dumps(value, ensure_ascii=False)),
        )

    def kv_delete(self, scope: str, key: str) -> None:
        self._write("DELETE FROM kv WHERE scope = ? AND key = ?", (scope, key))


def _payment(row: sqlite3.Row) -> Payment:
    return Payment(
        provider=row["provider"],
        external_id=row["external_id"],
        user_id=row["user_id"],
        days=row["days"],
        amount=row["amount"],
        currency=row["currency"],
        status=row["status"],
    )


def _child(row: sqlite3.Row) -> ChildBot:
    return ChildBot(
        id=row["id"],
        owner_id=row["owner_id"],
        token=row["token"],
        username=row["username"],
        plugin=row["plugin"],
        active=bool(row["active"]),
    )
