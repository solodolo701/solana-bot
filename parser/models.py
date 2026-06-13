from enum import Enum
from typing import Optional
from pydantic import BaseModel


class SignalType(str, Enum):
    FRESH_ENTRY = "FRESH_ENTRY"
    HOLD_UPDATE = "HOLD_UPDATE"
    PROGRESS_UPDATE = "PROGRESS_UPDATE"
    UNKNOWN = "UNKNOWN"


class Sentiment(str, Enum):
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"


class Urgency(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class McapTier(str, Enum):
    ULTRA_EARLY = "ULTRA_EARLY"  # < 1M  → TP1 +150%, TP2 +500%, SL -40%, time 4h
    EARLY = "EARLY"              # 1–5M  → TP1 +100%, TP2 +300%, SL -35%, time 3h
    MID = "MID"                  # 5–20M → TP1  +75%, TP2 +200%, SL -30%, time 2h
    LATE = "LATE"                # 20M+  → TP1  +60%, TP2 +120%, SL -25%, time 2h


# TP/SL defaults keyed by tier
TIER_DEFAULTS: dict[McapTier, dict] = {
    McapTier.ULTRA_EARLY: {"tp1": 150.0, "tp2": 500.0, "sl": -40.0, "time_sl_h": 4.0},
    McapTier.EARLY:       {"tp1": 100.0, "tp2": 300.0, "sl": -35.0, "time_sl_h": 3.0},
    McapTier.MID:         {"tp1":  75.0, "tp2": 200.0, "sl": -30.0, "time_sl_h": 2.0},
    McapTier.LATE:        {"tp1":  60.0, "tp2": 120.0, "sl": -25.0, "time_sl_h": 2.0},
}


class ParsedSignal(BaseModel):
    contract_address: str
    ticker: str
    signal_type: SignalType
    conviction: int  # 1–10
    sentiment: Sentiment
    urgency: Urgency

    entry_mcap_usd: Optional[float] = None   # caller's stated entry mcap
    entry_mcap_tier: Optional[McapTier] = None
    target_mcap_usd: Optional[float] = None  # e.g. "break above 50m"

    # TP/SL filled in from TIER_DEFAULTS (or overridden by explicit target)
    tp1_pct: Optional[float] = None
    tp2_pct: Optional[float] = None
    sl_pct: Optional[float] = None
    time_sl_hours: Optional[float] = None

    has_catalyst: bool = False
    catalyst_hint: Optional[str] = None     # e.g. "world cup starts in few hours"
    has_social_proof: bool = False           # Ansem, chads, whales mentioned
    caller_is_buying: bool = False           # "personally I'm apeing"
    is_pump_fun: bool = False                # CA ends in 'pump'

    channel: str = ""
    raw_text: str = ""
