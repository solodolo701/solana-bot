import aiosqlite

DB_PATH = "bot.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id                  TEXT PRIMARY KEY,
    ca                  TEXT NOT NULL,
    ticker              TEXT,
    entry_time          DATETIME,
    entry_price         REAL,
    entry_mcap          REAL,
    entry_sol           REAL,
    tokens_held         REAL,
    tp1_pct             REAL,
    tp2_pct             REAL,
    sl_pct              REAL,
    status              TEXT DEFAULT 'OPEN',
    tp1_hit             INTEGER DEFAULT 0,
    trailing_sl_active  INTEGER DEFAULT 0,
    trailing_sl_price   REAL,
    token_name          TEXT,
    exit_time           DATETIME,
    exit_price          REAL,
    pnl_sol             REAL,
    source_channel      TEXT,
    tx_buy_hash         TEXT,
    tx_sell_hash        TEXT
);

CREATE TABLE IF NOT EXISTS signals (
    id              TEXT PRIMARY KEY,
    received_at     DATETIME,
    channel         TEXT,
    ca              TEXT,
    ticker          TEXT,
    signal_type     TEXT,
    conviction      INTEGER,
    sentiment       TEXT,
    gate_result     TEXT DEFAULT 'PENDING',
    entry_mcap      REAL,
    target_mcap     REAL,
    gate_reason     TEXT,
    traded          INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS blacklist (
    ca      TEXT PRIMARY KEY,
    reason  TEXT,
    added   DATETIME
);
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db
