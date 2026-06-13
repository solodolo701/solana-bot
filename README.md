# Solana Memecoin Trading Bot — Full Build Plan

**Capital: $100 in SOL | Chain: Solana | Signal Source: Telegram alpha channels**

-----

## Executive Summary

This bot listens to Telegram alpha call channels in real time, uses an LLM to parse contract addresses (CAs) and sentiment from raw messages, runs a multi-layer token safety gate, executes buys via Jupiter Ultra API on Solana, and monitors positions for dynamic TP/SL exit. Everything runs as a single Python process, deployable in Claude Code locally or on a VPS.

-----

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                   TELEGRAM LISTENER                         │
│   Telethon client — monitors N signal channels in parallel  │
└──────────────────────────┬──────────────────────────────────┘
                           │ raw message text
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  SIGNAL PARSER (LLM)                        │
│   Claude Haiku (cheap) extracts:                            │
│   – contract_address (CA)                                   │
│   – conviction score (1–10)                                 │
│   – sentiment label (BULLISH / NEUTRAL / BEARISH)           │
│   – explicit TP/SL if stated in message                     │
│   – narrative tags (meme, AI, animal, political…)           │
└──────────────────────────┬──────────────────────────────────┘
                           │ structured signal
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                   SAFETY GATE                               │
│   Layer 1 – RugCheck.xyz API  (risk score, mint/freeze)     │
│   Layer 2 – DexScreener API   (liquidity, age, volume)      │
│   Layer 3 – Jupiter quote sim (can we actually sell it?)    │
│   → PASS or REJECT with reason logged                       │
└──────────────────────────┬──────────────────────────────────┘
                           │ safe signal
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  POSITION SIZER                             │
│   Fixed: 5% of portfolio per trade = ~$5 starting          │
│   Scales with conviction score from LLM                     │
│   Hard cap: max 3 concurrent open positions                 │
│   Daily loss limit: -20% of portfolio → bot pauses          │
└──────────────────────────┬──────────────────────────────────┘
                           │ order params
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  TRADE EXECUTOR                             │
│   Jupiter Ultra API + Jito bundle submission                │
│   Priority fee = auto (dynamic from recent blocks)          │
│   Slippage = 5–15% (adaptive for memecoin liquidity)        │
│   Anti-MEV: Jito DontFront + private submission             │
└──────────────────────────┬──────────────────────────────────┘
                           │ position open
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                POSITION MONITOR (async loop)                │
│   Polls DexScreener price every 15s                         │
│   Evaluates dynamic TP/SL from sentiment engine             │
│   Triggers sell → back through Trade Executor               │
└──────────────────────────┬──────────────────────────────────┘
                           │ trade closed
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              CONTROL & NOTIFICATION BOT                     │
│   Your own Telegram bot (BotFather)                         │
│   Reports: signal received, buy confirmed, sell confirmed   │
│   Commands: /status /pause /resume /positions /pnl          │
└─────────────────────────────────────────────────────────────┘
```

-----

## 2. Component Deep Dive

### 2.1 Telegram Listener (Telethon)

**Library:** Telethon (Python MTProto client)
**Auth:** Your personal Telegram account API credentials from my.telegram.org (api_id + api_hash). The listener runs as *your account*, not a bot — this is required to read private/channel messages without being a member of every channel as a bot.

**How it works:**

- Register an event handler with `@client.on(events.NewMessage(chats=[list_of_channels]))`
- Fires on every new message across all monitored channels simultaneously
- No polling delay — push-based via MTProto long-polling
- Handles `FloodWaitError` automatically (Telethon built-in)

**What channels to monitor (starting list):**

- `@gmgnsignalsol` — GMGN.AI automated new pair signals
- `@dextoolssolanapumps` — DEXTools Solana early launches
- Manual alpha call groups (add as you find trusted ones)

**Message pre-filter before LLM call (saves tokens/cost):**

- Must contain a string matching Solana CA pattern: `[1-9A-HJ-NP-Za-km-z]{32,44}`
- Discard if message is from a bot replying to itself (forward loops)
- Discard if CA seen in last 30 minutes (dedup cache)

-----

### 2.2 Signal Parser — LLM Layer

**Model:** Claude Haiku (cheapest, sub-1s latency, structured output)
**Alternative:** DeepSeek-chat via OpenAI-compatible API (even cheaper)

**Structured output schema (Pydantic):**

```python
class ParsedSignal(BaseModel):
    contract_address: str
    chain: str                    # always "solana" as guard
    conviction: int               # 1–10 (LLM-estimated)
    sentiment: str                # BULLISH / NEUTRAL / BEARISH
    narrative: str                # meme category tag
    explicit_tp_pct: float | None # e.g. 50.0 = take profit at +50%
    explicit_sl_pct: float | None # e.g. -25.0 = stop loss at -25%
    caller_urgency: str           # HIGH / MEDIUM / LOW
    red_flags: list[str]          # anything LLM flags as suspicious
```

**Prompt design:**
System prompt instructs Haiku to act as a Solana trading signal extractor, output ONLY valid JSON, never hallucinate CAs, and return `null` for any field it cannot determine with confidence.

**Cost estimate:** ~500 tokens per message × $0.00025/1K = $0.000125/signal → negligible.

-----

### 2.3 Safety Gate — Three-Layer Filter

Every CA must pass all three layers before any capital is committed.

#### Layer 1: RugCheck.xyz API

- Endpoint: `GET https://api.rugcheck.xyz/v1/tokens/{mint}/report`
- No API key required for basic reads
- **Pass criteria:**
  - `score_normalised < 500` (Good/Low on their scale)
  - Mint authority = disabled (cannot print more tokens)
  - Freeze authority = disabled (cannot freeze your tokens)
  - LP tokens burned or locked ≥ 80%
  - Top 10 holders < 30% of supply

#### Layer 2: DexScreener API

- Endpoint: `GET https://api.dexscreener.com/latest/dex/tokens/{ca}`
- Free, no key needed
- **Pass criteria:**
  - Liquidity ≥ $15,000 (too low = instant rug)
  - Token age ≥ 5 minutes (avoid launch-second snipes)
  - At least 1 active trading pair on Raydium or Orca
  - 24h volume > $5,000

#### Layer 3: Jupiter Quote Simulation (honeypot check)

- Call Jupiter quote API: `SOL → token` then immediately `token → SOL`
- If sell quote fails or output < 50% of buy output at same size: **REJECT**
- This detects honeypots that block or heavily tax sells

**Timing:** All three layers run concurrently (asyncio.gather). Total gate latency: ~300–800ms. Acceptable given memecoin windows are usually minutes, not seconds.

-----

### 2.4 Position Sizing Engine

**Philosophy:** Protect capital above all. With $100 starting capital, survival beats maximizing any single trade.

```
Base position size = portfolio_value × 0.05  ($5 at start)

Conviction multiplier:
  score 8–10 → 1.5× (max $7.50)
  score 5–7  → 1.0× (base $5.00)
  score 1–4  → 0.5× (skip or $2.50 minimum)

Hard constraints:
  Max single position: $15 (15% of starting capital)
  Max concurrent positions: 3
  Daily loss limit: -$20 → bot suspends trading, sends alert
  Reserve buffer: always keep ≥0.01 SOL for gas
```

-----

### 2.5 Trade Executor

**Buy flow:**

1. Get Jupiter Ultra quote: `SOL → target_token`, amount from sizer
1. Compute priority fee: median of recent 150 blocks × 1.25 multiplier
1. Build versioned transaction with compute budget instruction
1. Submit via Jito block engine endpoint (not public RPC) for MEV protection
1. Confirm via `confirmTransaction()` with 30s timeout
1. Log: tx_hash, entry_price, tokens_received, timestamp

**Key parameters:**

- Slippage: start at 5%, retry at 10%, final retry at 15% (3 attempts max)
- Jito tip: 0.001–0.01 SOL depending on urgency (LLM caller_urgency field)
- Transaction: versioned + Address Lookup Tables (smaller, faster)

**Sell flow:** identical path but `target_token → SOL`. Always sell entire position (no partial exits at this capital level — too complex for $100).

**RPC:** Use a private RPC (QuickNode free tier or Helius free tier) — public mainnet RPC is unreliable under load.

-----

### 2.6 Position Monitor & Exit Engine

Runs as an `asyncio` background task per open position.

**Polling:** DexScreener price endpoint every 15 seconds.

**Exit decision tree:**

```
IF explicit TP from signal → use it directly
ELIF explicit SL from signal → use it directly
ELSE → dynamic mode:

  TP calculation:
    conviction 8–10: TP at +80% 
    conviction 5–7:  TP at +50%
    conviction 1–4:  TP at +30%

  SL calculation (always fixed regardless of conviction):
    Hard SL: -30% from entry
    Trailing SL: once position is +20% in profit, trail SL 
                 at entry price (lock in breakeven)
    Once +40%, trail SL 20% below current price

  Time-based SL:
    If no 20% gain within 2 hours → sell at market
    (Memecoins either pump fast or they don't)
```

**Sentiment-adjusted SL (advanced mode):**
If subsequent messages in monitored channels mention the token negatively (LLM re-evaluates), tighten SL to -15% regardless of current level.

-----

### 2.7 Control & Notification Bot

A separate Telegram bot (created via @BotFather) that you interact with.

**Inbound commands:**

```
/status     — overall bot health, uptime, SOL balance
/positions  — list open positions with current P&L
/pnl        — daily/weekly/all-time realized P&L
/pause      — halt new signal intake (positions still monitored)
/resume     — resume signal intake
/close [CA] — manually close a specific position
/config     — view/change TP/SL/position size settings
/whitelist  — add a channel to monitor
/blacklist  — add a token CA to never trade again
```

**Outbound alerts (automatic):**

- Signal received + parsed summary
- Safety gate pass/fail with reason
- Buy confirmed: CA, entry price, size, TP/SL levels
- Sell confirmed: CA, exit price, realized P&L, hold duration
- Daily loss limit hit → bot paused
- Fatal error / exception

-----

## 3. Technology Stack

|Layer               |Technology                    |Notes                             |
|--------------------|------------------------------|----------------------------------|
|Language            |Python 3.11+                  |asyncio throughout                |
|Telegram listener   |Telethon 1.x                  |MTProto, your account             |
|Telegram control bot|python-telegram-bot           |Separate bot token                |
|LLM parsing         |Anthropic Claude Haiku via API|Structured output / instructor    |
|Signal schema       |Pydantic v2                   |Validation + type safety          |
|Safety Layer 1      |RugCheck.xyz REST API         |Free, no key needed               |
|Safety Layer 2      |DexScreener REST API          |Free, no key needed               |
|Safety Layer 3      |Jupiter Quote API             |Free, public                      |
|Trade execution     |Jupiter Ultra API             |REST, versioned txns              |
|MEV protection      |Jito block engine             |Via mainnet-beta Jito RPC         |
|Solana SDK          |solders + solana-py           |Low-level tx building             |
|State persistence   |SQLite (aiosqlite)            |Positions, trade log, CA blacklist|
|Config              |.env file + pydantic-settings |All secrets in env vars           |
|Logging             |structlog                     |JSON-structured for easy parsing  |
|Deployment          |Python process on VPS or local|tmux / systemd                    |

-----

## 4. Data Models (SQLite)

### positions table

```sql
CREATE TABLE positions (
  id            TEXT PRIMARY KEY,
  ca            TEXT NOT NULL,
  token_name    TEXT,
  entry_time    DATETIME,
  entry_price   REAL,
  entry_sol     REAL,
  tokens_held   REAL,
  tp_pct        REAL,
  sl_pct        REAL,
  status        TEXT,  -- OPEN / CLOSED_TP / CLOSED_SL / CLOSED_TIME / CLOSED_MANUAL
  exit_time     DATETIME,
  exit_price    REAL,
  pnl_sol       REAL,
  source_channel TEXT,
  tx_buy_hash   TEXT,
  tx_sell_hash  TEXT
);
```

### signals table (all signals including rejected)

```sql
CREATE TABLE signals (
  id            TEXT PRIMARY KEY,
  received_at   DATETIME,
  channel       TEXT,
  ca            TEXT,
  conviction    INTEGER,
  sentiment     TEXT,
  gate_result   TEXT,  -- PASS / REJECT_RUGCHECK / REJECT_DEX / REJECT_HONEYPOT / REJECT_DUPLICATE
  gate_reason   TEXT,
  traded        BOOLEAN
);
```

### blacklist table

```sql
CREATE TABLE blacklist (
  ca      TEXT PRIMARY KEY,
  reason  TEXT,
  added   DATETIME
);
```

-----

## 5. File Structure (Claude Code project)

```
solana-signal-bot/
├── .env                          # secrets (never commit)
├── .env.example                  # template
├── requirements.txt
├── README.md
├── main.py                       # entry point, wires everything together
├── config.py                     # pydantic-settings config model
│
├── listener/
│   ├── __init__.py
│   ├── telegram_listener.py      # Telethon client + channel watchers
│   └── message_filter.py        # pre-LLM CA regex + dedup cache
│
├── parser/
│   ├── __init__.py
│   ├── llm_parser.py             # Claude Haiku call + structured output
│   └── models.py                 # ParsedSignal Pydantic model
│
├── safety/
│   ├── __init__.py
│   ├── rugcheck.py               # Layer 1
│   ├── dexscreener.py            # Layer 2
│   ├── honeypot.py               # Layer 3 (Jupiter simulation)
│   └── gate.py                   # orchestrates all 3 layers concurrently
│
├── sizing/
│   ├── __init__.py
│   └── sizer.py                  # conviction-based position sizing
│
├── executor/
│   ├── __init__.py
│   ├── jupiter.py                # quote + swap via Jupiter Ultra API
│   ├── jito.py                   # bundle submission + MEV protection
│   └── wallet.py                 # keypair management, balance check
│
├── monitor/
│   ├── __init__.py
│   ├── position_monitor.py       # async polling + exit logic
│   └── exit_engine.py            # TP/SL/time/sentiment exit rules
│
├── notification/
│   ├── __init__.py
│   └── bot.py                    # python-telegram-bot control interface
│
├── storage/
│   ├── __init__.py
│   ├── database.py               # aiosqlite init + migrations
│   └── models.py                 # Position, Signal, Blacklist dataclasses
│
└── utils/
    ├── __init__.py
    ├── logger.py                  # structlog setup
    └── helpers.py                 # retry decorator, lamport conversions
```

-----

## 6. Environment Variables

```bash
# Telegram
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_PHONE=
TELEGRAM_CONTROL_BOT_TOKEN=   # BotFather token for your control bot
TELEGRAM_CHAT_ID=              # your chat ID for notifications

# Solana
SOLANA_RPC_URL=                # e.g. https://mainnet.helius-rpc.com/?api-key=...
JITO_RPC_URL=                  # https://mainnet.block-engine.jito.wtf/api/v1
WALLET_PRIVATE_KEY=            # base58 encoded — keep safe

# LLM
ANTHROPIC_API_KEY=

# Trading params (overrides defaults)
MAX_POSITION_PCT=0.05
MAX_CONCURRENT_POSITIONS=3
DAILY_LOSS_LIMIT_PCT=0.20
DEFAULT_TP_PCT=50
DEFAULT_SL_PCT=-30
TIME_SL_HOURS=2

# Channels to monitor (comma-separated)
SIGNAL_CHANNELS=@gmgnsignalsol,@dextoolssolanapumps
```

-----

## 7. Risk Management Summary

|Risk                 |Mitigation                                                    |
|---------------------|--------------------------------------------------------------|
|Rug pull             |RugCheck gate: mint/freeze off, LP locked ≥80%                |
|Honeypot             |Jupiter sell simulation before entry                          |
|Low liquidity        |DexScreener gate: min $15k liquidity                          |
|Sandwich / MEV attack|Jito bundle submission + DontFront                            |
|Runaway loss         |-30% hard SL per trade, -20% daily portfolio limit            |
|Bot runaway / bug    |Daily loss limit auto-pause + manual /pause command           |
|Key compromise       |Private key in env var only, separate hot wallet with max $100|
|Slippage blowout     |3-tier slippage retry (5% → 10% → 15%), abort if all fail     |
|False signals        |Conviction threshold: only trade score ≥5, sentiment BULLISH  |
|Capital erosion      |Max 3 positions, 5% base sizing, time-based SL at 2h          |

**The #1 risk not fully mitigable:** 98.7% of Solana tokens on Pump.fun are pump-and-dump schemes (Solidus Labs data). The safety gate filters heavily but cannot be 100% accurate. With $100 capital, treat this as a learning exercise and expect to lose some or all of it. Never fund the hot wallet beyond your risk tolerance.

-----

## 8. Build Sequence for Claude Code

Build in the order below. The sequence follows the actual data-flow of the pipeline — each phase produces output that the next phase consumes. Every phase is independently testable without real capital, and without needing any subsequent phase to be built.

A `DRY_RUN=true` environment flag is introduced in Phase 0 and respected by every module that touches money or on-chain state. Never disable it until Phase 9.

### Phase Summary

| Phase | What You Build | Capital Needed | Testable Without Next Phase |
|-------|---------------|----------------|-----------------------------|
| 0 | Env, venv, deps, Telethon OTP auth | None | Yes — pip install + OTP flow |
| 1 | config.py, SQLite, logger, helpers | None | Yes — imports + DB creation |
| 2 | Signal parser, message filter | None (Claude API only) | Yes — feed test messages from a script |
| 3 | Telegram listener (read-only) | None | Yes — 30-min live listen session |
| 4 | Safety gate (3 layers) | None | Yes — test CAs from a script |
| 5 | Wallet, Jupiter quotes, RPC submit | Optional (DRY_RUN bypasses) | Yes with DRY_RUN=true |
| 6 | Sizer, exit engine, position monitor | None | Yes — pure unit tests |
| 7 | Control/notification bot | None | Yes — send /status manually |
| 8 | main.py integration, 48h paper run | None (PAPER_TRADE=true) | — |
| 9 | Live trading | $10 → $50 → $100 | — |

---

### Phase 0 — Environment Bootstrap (Day 0)

No Python code to write here. These steps are prerequisites for every phase that follows.

**0.1 Python environment**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

**0.2 Create `requirements.txt`**

Pin these versions — Telethon and solders have breaking API changes between minor releases:

```
telethon==1.36.0
python-telegram-bot==21.6
anthropic==0.34.2
pydantic==2.8.2
pydantic-settings==2.4.0
aiosqlite==0.20.0
httpx==0.27.2
structlog==24.4.0
solders==0.21.0
solana==0.34.3
instructor==1.4.3
```

```bash
pip install -r requirements.txt
```

**0.3 Create `.env.example`**

```bash
# ── Telegram listener (your personal account from my.telegram.org) ───────────
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_PHONE=+1234567890

# ── Telegram control bot (token from @BotFather) ─────────────────────────────
TELEGRAM_CONTROL_BOT_TOKEN=
TELEGRAM_CHAT_ID=              # your personal chat ID — send /start to @userinfobot

# ── Solana ────────────────────────────────────────────────────────────────────
SOLANA_RPC_URL=                # Helius free tier: https://mainnet.helius-rpc.com/?api-key=...
JITO_RPC_URL=https://mainnet.block-engine.jito.wtf/api/v1
WALLET_PRIVATE_KEY=            # base58 encoded private key — keep safe

# ── LLM ──────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY=

# ── Trading parameters ────────────────────────────────────────────────────────
MAX_POSITION_PCT=0.05
MAX_CONCURRENT_POSITIONS=3
DAILY_LOSS_LIMIT_PCT=0.20
DEFAULT_TP_PCT=50
DEFAULT_SL_PCT=-30
TIME_SL_HOURS=2

# ── Channels to monitor (comma-separated @usernames or numeric IDs) ───────────
SIGNAL_CHANNELS=@gmgnsignalsol,@dextoolssolanapumps

# ── Safety switches ───────────────────────────────────────────────────────────
DRY_RUN=true          # true = no real swaps ever executed
PAPER_TRADE=true      # true = log what would be traded, don't call executor
MIN_CONVICTION=5      # signals below this score are discarded
```

Copy to `.env` and fill in your credentials. Confirm `.gitignore` includes `.env` and `session/`.

**0.4 Telethon one-time interactive authentication**

Telethon authenticates as *your personal Telegram account* (not a bot token). The first run requires an interactive terminal session to receive a one-time code via SMS or the Telegram app. This cannot be automated. Run this once manually, then delete the script:

```python
# auth_once.py — run interactively ONE TIME, then delete
from telethon.sync import TelegramClient
import os
from dotenv import load_dotenv
load_dotenv()

client = TelegramClient(
    "session/telethon.session",
    int(os.environ["TELEGRAM_API_ID"]),
    os.environ["TELEGRAM_API_HASH"],
)
client.start(phone=os.environ["TELEGRAM_PHONE"])
print("Auth complete. session/telethon.session created.")
client.disconnect()
```

```bash
mkdir -p session
python auth_once.py
```

Enter the code Telegram sends to your app or phone. This creates `session/telethon.session` — add it to `.gitignore`. You will not need to authenticate again unless the session is invalidated.

**Phase 0 verification:** `pip install` completes with no errors. `.env` file exists and is populated. `session/telethon.session` is a non-zero file.

---

### Phase 1 — Foundation Layer (Day 1)

- [ ] `config.py` — pydantic-settings `Settings` class loading all `.env` variables, including `DRY_RUN: bool = True` and `PAPER_TRADE: bool = True`. All other modules import from here; no module reads `.env` directly.
- [ ] `storage/database.py` — aiosqlite init, creates all three tables on startup, `migrate()` coroutine safe to call on every restart.
- [ ] `utils/logger.py` — structlog JSON output; injects `dry_run` and `paper_trade` fields into every log line so mode is always visible in logs.
- [ ] `utils/helpers.py` — `@retry` async decorator with exponential backoff, `lamports_to_sol()`, `sol_to_lamports()`, `short_address()`.

**Test:** `python -c "from config import settings; print(settings.DRY_RUN)"` → prints `True`. `python -c "import asyncio; from storage.database import init_db; asyncio.run(init_db())"` → creates `bot.db`. `sqlite3 bot.db .tables` → shows all three tables.

---

### Phase 2 — Signal Parser & Message Filter (Day 1–2)

Build the LLM parsing pipeline first — it has no Solana dependency, costs only a few API cents to test, and lets you validate that signal data is actually usable before writing any wallet code.

- [ ] `parser/models.py` — `ParsedSignal` Pydantic model (see Section 2.2).
- [ ] `parser/llm_parser.py` — async `parse_message(text: str) -> ParsedSignal | None` using the Anthropic client with `instructor`. Returns `None` on malformed output rather than raising. Logs token cost per call.
- [ ] `listener/message_filter.py` — `MessageFilter` class: Solana CA regex (`[1-9A-HJ-NP-Za-km-z]{32,44}`), in-memory dedup TTL cache (default 30 minutes). `filter(text: str) -> FilterResult`.

**Test:** Create `tests/test_parser.py` with 4–5 hardcoded example Telegram messages (one with CA, one without, one ambiguous, one that looks like a rug call). Run `parse_message()` against each and print results. Verify CA extraction, conviction scoring, and `None` on garbage input. Expected total cost: under $0.01.

---

### Phase 3 — Telegram Listener (Day 2)

Connect the parser to live Telegram data. Requires the session file from Phase 0.

- [ ] `listener/telegram_listener.py` — `TelegramListener` class. Loads channel list from `settings.SIGNAL_CHANNELS`. Registers `@client.on(events.NewMessage)` handler. For each message: runs `MessageFilter`, then `parse_message()`, then writes to the `signals` table with `gate_result=PENDING`, `traded=False`. No safety gate, no executor — listen, parse, and log only. Handles `FloodWaitError` (Telethon raises it automatically; log and wait).

**Test:** Run `listener/telegram_listener.py` as a standalone script for 30–60 minutes. Confirm signal log lines appear. Open `bot.db` and verify the `signals` table is accumulating rows. Confirm duplicate CAs within 30 minutes are deduplicated. This is first contact with real-world signal quality.

---

### Phase 4 — Safety Gate (Day 3)

Safety checking requires a CA as input — that's why this phase comes after the listener. All three external APIs are free and require no wallet.

- [ ] `safety/rugcheck.py` — async `check_rugcheck(ca: str) -> RugCheckResult`. Hits RugCheck.xyz REST API, returns `is_safe`, `risk_score`, `mint_authority_disabled`, `freeze_authority_disabled`, `lp_burned_pct`, `top10_holder_pct`, `fail_reason`. Uses `@retry`. Pass thresholds from Section 2.3.
- [ ] `safety/dexscreener.py` — async `check_dexscreener(ca: str) -> DexResult`. Returns `is_safe`, `liquidity_usd`, `token_age_minutes`, `volume_24h`, `fail_reason`.
- [ ] `safety/honeypot.py` — async `check_honeypot(ca: str) -> HoneypotResult`. Calls Jupiter quote API twice (buy sim, sell sim). Returns `is_safe`, `sell_ratio`, `fail_reason`. This only requests quotes — no transaction is ever submitted.
- [ ] `safety/gate.py` — async `run_gate(ca: str) -> GateDecision`. Uses `asyncio.gather()` to run all three checks concurrently. Returns `PASS` or first `REJECT_*` reason. Updates the `signals` table row with the gate result.

**Test:** Create `tests/test_gate.py`. Run the gate against: one known-good token, one known-rug CA, one very-new low-liquidity token. Verify correct pass/fail with the right `fail_reason`. All three layers should resolve in under 1 second concurrently.

---

### Phase 5 — Wallet & Solana Layer (Day 3–4)

Only now do wallet credentials become necessary. `DRY_RUN` must be respected throughout — when `true`, no transaction is ever submitted.

- [ ] `executor/wallet.py` — `load_keypair()` from base58 private key. `get_sol_balance() -> float`. `has_gas_reserve() -> bool` (balance ≥ 0.01 SOL). When `DRY_RUN=true`, `get_sol_balance()` returns a mock value of `0.5` so downstream logic has a sensible number.
- [ ] `executor/jupiter.py` — async `get_quote(input_mint, output_mint, amount_lamports) -> QuoteResponse`. async `build_swap_transaction(quote) -> Transaction | None`. When `DRY_RUN=true`, logs the intended swap and returns `None`.
- [ ] `executor/jito.py` — async `submit_transaction(tx) -> str`. **Start with standard RPC submission** (`settings.SOLANA_RPC_URL`). Jito bundle submission is an optional upgrade in Phase 9, not required for the bot to trade. When `DRY_RUN=true`, logs `[DRY_RUN] would submit tx` and returns `DRYRUN-{uuid}`.

**Test (DRY_RUN=true, no capital needed):** Run wallet.py standalone, verify mock balance is returned with no RPC calls made. Optionally (with real key, DRY_RUN=false): call `get_sol_balance()` against mainnet and verify correct balance. Do NOT test swap submission until Phase 8.

---

### Phase 6 — Position Sizer, Exit Engine & Monitor (Day 4)

Pure Python business logic — no Solana or Telegram dependency.

- [ ] `sizing/sizer.py` — `calculate_position_size(conviction: int, portfolio_sol: float, open_positions: int) -> float | None`. Returns `None` when constraints block the trade (max positions, daily loss limit, conviction below minimum). All sizing rules from Section 2.4.
- [ ] `monitor/exit_engine.py` — `evaluate_exit(position: Position, current_price: float) -> ExitDecision`. Pure function, no I/O. Evaluates all TP/SL/trailing/time rules from Section 2.6.
- [ ] `monitor/position_monitor.py` — async `monitor_positions(db, executor)` loop. Polls DexScreener every 15 seconds per open position. Calls `evaluate_exit()`. When `PAPER_TRADE=true`, logs the exit decision but does NOT call the executor.

**Test:** `tests/test_sizer.py` and `tests/test_exit_engine.py` — pure unit tests, no network calls. Test sizer with: high conviction, low conviction, max positions open, daily limit reached. Test exit engine with: TP hit, SL hit, time SL, trailing SL activation.

---

### Phase 7 — Control & Notification Bot (Day 4–5)

- [ ] `notification/bot.py` — `python-telegram-bot` Application. Command handlers for `/status`, `/positions`, `/pnl`, `/pause`, `/resume`, `/close`, `/config`, `/whitelist`, `/blacklist`. Outbound `send_alert(text: str)` used by all other modules. Bot silently rejects commands from any `chat_id` other than `settings.TELEGRAM_CHAT_ID` — this prevents unauthorized control. When `DRY_RUN=true`, prepends `[DRY_RUN]` to every outbound alert.

**Test:** Start the bot, send `/status` from your Telegram account — verify a response arrives. Send the same command from a different account — verify it is silently ignored. Trigger a test alert from code and verify it arrives in under 2 seconds.

---

### Phase 8 — Integration + 48-Hour Paper Run (Day 5)

- [ ] `main.py` — starts all coroutines with `asyncio.gather()`: Telegram listener, position monitor loop, control bot polling. Logs startup state including `DRY_RUN` and `PAPER_TRADE` values prominently. Registers `SIGTERM`/`SIGINT` handlers for clean shutdown: close DB connections, disconnect Telethon client, send shutdown alert.

**Test (48-hour paper run, PAPER_TRADE=true, zero capital at risk):**

1. Start `python main.py` in a `tmux` session.
2. Confirm signals flow: listener → parser → gate → sizer → `[PAPER_TRADE] would buy CA=... size=...` log lines.
3. Check `bot.db` accumulates rows with correct gate results.
4. Send `/positions` — should return paper positions with simulated P&L.
5. After 24 hours: review gate pass rate, signal volume per channel, LLM parse quality. Tune `MIN_CONVICTION` if needed.

---

### Phase 9 — Live with Micro Capital (Day 6+)

Only proceed when the 48-hour paper run produced clean logs with no uncaught exceptions.

1. Set `PAPER_TRADE=false`, keep `DRY_RUN=true` for one hour. Verify `[DRY_RUN] would submit tx` lines appear in logs at trade time — confirming the execution path is reached.
2. Set `DRY_RUN=false`. Fund the hot wallet with **$10 in SOL only** (not the full $100).
3. Run live for 48 hours. Review every trade manually via `/positions` and the `signals` table.
4. If execution is clean and losses are within expected bounds → scale to $50, then $100.

**Optional Jito upgrade (after live trading is stable):** Add Jito bundle submission in `executor/jito.py`, gated behind `USE_JITO=false` in `.env`. Standard RPC is functionally correct — Jito reduces MEV exposure but is not required for the bot to trade.

-----

## 9. Claude Code Prompting Strategy

When building in Claude Code, use these prompt patterns:

**Starting a module:**

> "Build `safety/rugcheck.py`. It should make an async GET request to `https://api.rugcheck.xyz/v1/tokens/{mint}/report`, parse the JSON, and return a `RugCheckResult` dataclass with fields: `is_safe: bool`, `risk_score: int`, `mint_authority_disabled: bool`, `freeze_authority_disabled: bool`, `lp_burned_pct: float`, `top10_holder_pct: float`, `fail_reason: str | None`. Pass threshold: risk_score < 500 AND mint disabled AND freeze disabled AND lp_burned_pct >= 80 AND top10_holder_pct < 30. Add retry logic with exponential backoff (max 3 attempts)."

**Adding to an existing module:**

> "Add a `DRY_RUN` mode flag to `executor/jupiter.py`. When `DRY_RUN=true` in .env, all swap calls should log the intended trade details and return a mock transaction hash starting with 'DRYRUN-' instead of executing on-chain."

**Debugging:**

> "The safety gate is running all 3 checks sequentially instead of concurrently. Show me how to use `asyncio.gather()` to run `rugcheck()`, `dexscreener()`, and `honeypot()` in parallel and collect all results."

-----

## 10. Monitoring & Iteration

**Week 1 metrics to track:**

- Signals received per day (from each channel)
- Gate pass rate (% making it through all 3 layers)
- Win rate of executed trades
- Average hold time
- Average P&L per trade
- Which channels produce highest-conviction wins

**Iteration strategy:**

- After 20+ trades: analyze which channel/conviction combos win most
- Tighten gate if too many near-misses pass
- Adjust time-SL if most losses come from time rather than price
- Add more channels that show high signal quality

**Channels to evaluate for quality:**

- Track: did the called token pump within 2h of signal?
- Build a per-channel win_rate score in the signals table
- Auto-deprioritize channels with <30% win rate after 10+ signals

-----

*Built for: FreshSolutions Jozsef | Capital: $100 SOL | Last updated: June 2026*
