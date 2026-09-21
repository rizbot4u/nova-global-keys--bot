"""SQLite storage with Fernet-encrypted user API keys."""
import os
import sqlite3
from contextlib import contextmanager
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.path.expanduser(os.environ.get("NOVA_DB", "./nova.db"))
_fernet = Fernet(os.environ["ENCRYPTION_KEY"].encode())


def enc(v: str) -> str:
    return _fernet.encrypt(v.encode()).decode()


def dec(v: str) -> str:
    return _fernet.decrypt(v.encode()).decode()


@contextmanager
def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id   INTEGER PRIMARY KEY,
            username      TEXT,
            dkhyr_balance REAL DEFAULT 0,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS api_keys (
            telegram_id    INTEGER,
            exchange       TEXT,
            api_key        TEXT,
            api_secret     TEXT,
            api_passphrase TEXT,
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (telegram_id, exchange)
        );
        CREATE TABLE IF NOT EXISTS trades (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            exchange    TEXT,
            symbol      TEXT,
            side        TEXT,
            qty         REAL,
            price       REAL,
            order_id    TEXT,
            status      TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS bots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            name        TEXT,
            exchange    TEXT,
            symbol      TEXT,
            strategy    TEXT,
            params      TEXT,
            status      TEXT DEFAULT 'running'
        );
        """)


def ensure_user(tg_id: int, username: str = ""):
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users (telegram_id, username) VALUES (?, ?)",
                  (tg_id, username))


def save_keys(tg_id: int, exchange: str, key: str, secret: str, passphrase: str = None):
    with db() as c:
        c.execute("""
            INSERT INTO api_keys (telegram_id, exchange, api_key, api_secret, api_passphrase)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id, exchange) DO UPDATE SET
                api_key=excluded.api_key,
                api_secret=excluded.api_secret,
                api_passphrase=excluded.api_passphrase
        """, (tg_id, exchange, enc(key), enc(secret),
              enc(passphrase) if passphrase else None))


def get_keys(tg_id: int, exchange: str):
    with db() as c:
        row = c.execute("SELECT * FROM api_keys WHERE telegram_id=? AND exchange=?",
                        (tg_id, exchange)).fetchone()
    if not row:
        return None
    return {
        "key":        dec(row["api_key"]),
        "secret":     dec(row["api_secret"]),
        "passphrase": dec(row["api_passphrase"]) if row["api_passphrase"] else None,
    }


def list_connected(tg_id: int):
    with db() as c:
        return [r["exchange"] for r in
                c.execute("SELECT exchange FROM api_keys WHERE telegram_id=?", (tg_id,))]


def log_trade(tg_id, exchange, symbol, side, qty, price, order_id, status):
    with db() as c:
        c.execute("""INSERT INTO trades
                     (telegram_id, exchange, symbol, side, qty, price, order_id, status)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                  (tg_id, exchange, symbol, side, qty, price, order_id, status))
