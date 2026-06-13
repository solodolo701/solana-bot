from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Position:
    id: str
    ca: str
    ticker: str
    entry_time: datetime
    entry_price: float
    entry_mcap: float
    entry_sol: float
    tokens_held: float
    tp1_pct: float
    tp2_pct: float
    sl_pct: float
    status: str = "OPEN"  # OPEN / CLOSED_TP1 / CLOSED_TP2 / CLOSED_SL / CLOSED_TIME / CLOSED_MANUAL
    tp1_hit: bool = False
    trailing_sl_active: bool = False
    trailing_sl_price: Optional[float] = None
    token_name: Optional[str] = None
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    pnl_sol: Optional[float] = None
    source_channel: str = ""
    tx_buy_hash: Optional[str] = None
    tx_sell_hash: Optional[str] = None


@dataclass
class Signal:
    id: str
    received_at: datetime
    channel: str
    ca: str
    ticker: str
    signal_type: str  # FRESH_ENTRY / HOLD_UPDATE / PROGRESS_UPDATE / UNKNOWN
    conviction: int
    sentiment: str
    gate_result: str = "PENDING"  # PENDING / PASS / REJECT_* / MISSED_ENTRY
    entry_mcap: Optional[float] = None
    target_mcap: Optional[float] = None
    gate_reason: Optional[str] = None
    traded: bool = False


@dataclass
class Blacklist:
    ca: str
    reason: str
    added: datetime = field(default_factory=datetime.utcnow)
