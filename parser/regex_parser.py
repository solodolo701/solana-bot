"""
Regex-based signal parser — no API or LLM required.

Handles two channel formats observed in the wild:

Channel 1 (Instagram caller style):
  $TICKER
  $TICKER (UPDATE)
  $TICKER (2M)
  Body with thesis...
  Ca: <address>

Channel 2 (direct entry style):
  Buying/Aping some $TICKER here at 30m
  Body with thesis...
  <bare_address>
  https://dexscreener.com/solana/...
"""
import re
from typing import Optional

from parser.models import McapTier, ParsedSignal, Sentiment, SignalType, TIER_DEFAULTS, Urgency
from utils.helpers import parse_mcap_string

# ── Contract address ──────────────────────────────────────────────────────────
_CA_LABELED   = re.compile(r'Ca:\s*([1-9A-HJ-NP-Za-km-z]{32,44})', re.IGNORECASE)
_CA_BARE_LINE = re.compile(r'^([1-9A-HJ-NP-Za-km-z]{32,44})\s*$', re.MULTILINE)
_PUMP_FUN_CA  = re.compile(r'[1-9A-HJ-NP-Za-km-z]{28,40}pump$')

# ── Ticker ────────────────────────────────────────────────────────────────────
# Channel 2: action verb followed by $TICKER ("Aping some $MATCH here at 800k")
_TICKER_ACTION = re.compile(
    r'(?:Buying|Aping|Apeing|Grabbing|Grabbed|Parking)\s+(?:some\s+|a bag of\s+)?\$([A-Z]+)',
    re.IGNORECASE,
)
# Channel 1: $TICKER alone on a line (possibly followed by space + parenthetical)
_TICKER_LINE   = re.compile(r'^\$([A-Z]+)(?:\s+\([^)]*\))?$', re.MULTILINE)

# ── Entry market cap ──────────────────────────────────────────────────────────
# Channel 1 header: $SIPO (2M)
_MCAP_HEADER = re.compile(r'^\$[A-Z]+\s+\((\d+\.?\d*[KkMmBb])\)', re.MULTILINE)
# Channel 2 inline: "Buying $X here at 30m" or "Aping $X at 800k"
_MCAP_AT     = re.compile(r'\$[A-Z]+\s+(?:here\s+)?at\s+(\d+\.?\d*[KkMmBb])\b', re.IGNORECASE)
# Body: "around the 2M market cap" / "around the 1.5M range" / "2M mc"
_MCAP_BODY   = re.compile(
    r'(?:around|at)\s+(?:the\s+)?(\d+\.?\d*[KkMmBb])\s*(?:market cap|mc|mcap|range)\b',
    re.IGNORECASE,
)

# ── Target market cap (from progress updates) ─────────────────────────────────
# "break above 50m" / "target 100m" / "hit the 80m"
_MCAP_TARGET = re.compile(
    r'(?:break(?:ing)?\s+(?:above|through|out)|above|target|hit(?:ting)?)\s+(?:the\s+)?(\d+\.?\d*[KkMmBb])\b',
    re.IGNORECASE,
)

# ── Signal type ───────────────────────────────────────────────────────────────
_IS_UPDATE_TAG  = re.compile(r'\(UPDATE\)', re.IGNORECASE)
_FRESH_VERBS    = re.compile(r'\b(grabbed a bag|grabbing|buying|aping|apeing|aped in|parking)\b', re.IGNORECASE)
_HOLD_PHRASES   = re.compile(r'\b(still holding|holding strong|been holding|i\'?m holding)\b', re.IGNORECASE)
_ATH_NO_ENTRY   = re.compile(r'\b(smashed|hit|new)\s+(a\s+)?ath\b', re.IGNORECASE)

# ── Sentiment ─────────────────────────────────────────────────────────────────
_VERY_BULLISH = re.compile(
    r'\b(absolutely cooking|about to send|insane narrative|much more to come|going much higher|cooking for us)\b',
    re.IGNORECASE,
)
_BULLISH = re.compile(
    r'\b(bullish|cooking|looking good|moving well|holding well|holding up|should cook|'
    r'super bullish|narrative is|perfect time|early play|incredible chart)\b',
    re.IGNORECASE,
)
_BEARISH = re.compile(r'\b(rug|dump|scam|avoid|rekt|dead|honeypot|rugged)\b', re.IGNORECASE)

# ── Conviction modifiers ──────────────────────────────────────────────────────
_CALLER_BUYING = re.compile(
    r"personally\s+I'?m\s+ap[ie]|I\s+am\s+(?:also\s+)?ap[ie]|I'?ve?\s+(?:also\s+)?grabbed|"
    r"I'?m\s+(?:also\s+)?buying|aping\s+a\s+(?:decent|nice|big|large)\s+sized\s+bag",
    re.IGNORECASE,
)
_SOCIAL_PROOF = re.compile(r'\b(ansem|kol|chad|whale|influencer|big names?|notable)\b', re.IGNORECASE)
_CATALYST     = re.compile(
    r'\b(world cup|super ?bowl|election|listing|airdrop|announcement|event|'
    r'catalyst|starts in|happening now|happening soon|real.world)\b',
    re.IGNORECASE,
)
_URGENCY      = re.compile(
    r'\b(few hours?|today|tonight|imminent|don\'?t miss|last call|going now|right now)\b',
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────────────

def _extract_ca(text: str) -> Optional[str]:
    m = _CA_LABELED.search(text)
    if m:
        return m.group(1)
    for ca in _CA_BARE_LINE.findall(text):
        if len(ca) >= 32:
            return ca
    return None


def _extract_ticker(text: str) -> Optional[str]:
    m = _TICKER_ACTION.search(text)
    if m:
        return m.group(1).upper()
    m = _TICKER_LINE.search(text)
    if m:
        return m.group(1).upper()
    return None


def _extract_entry_mcap(text: str) -> Optional[float]:
    m = _MCAP_HEADER.search(text)
    if m:
        return parse_mcap_string(m.group(1))
    m = _MCAP_AT.search(text)
    if m:
        return parse_mcap_string(m.group(1))
    m = _MCAP_BODY.search(text)
    if m:
        return parse_mcap_string(m.group(1))
    return None


def _extract_target_mcap(text: str) -> Optional[float]:
    m = _MCAP_TARGET.search(text)
    if m:
        return parse_mcap_string(m.group(1))
    return None


def _mcap_tier(mcap_usd: Optional[float]) -> Optional[McapTier]:
    if mcap_usd is None:
        return None
    if mcap_usd < 1_000_000:
        return McapTier.ULTRA_EARLY
    if mcap_usd < 5_000_000:
        return McapTier.EARLY
    if mcap_usd < 20_000_000:
        return McapTier.MID
    return McapTier.LATE


def _signal_type(text: str) -> SignalType:
    if _IS_UPDATE_TAG.search(text):
        return SignalType.HOLD_UPDATE
    if _HOLD_PHRASES.search(text) and not _FRESH_VERBS.search(text):
        return SignalType.HOLD_UPDATE
    if _ATH_NO_ENTRY.search(text) and not _FRESH_VERBS.search(text):
        return SignalType.PROGRESS_UPDATE
    if _FRESH_VERBS.search(text):
        return SignalType.FRESH_ENTRY
    return SignalType.UNKNOWN


def _sentiment(text: str) -> Sentiment:
    if _BEARISH.search(text):
        return Sentiment.BEARISH
    if _VERY_BULLISH.search(text) or _BULLISH.search(text):
        return Sentiment.BULLISH
    return Sentiment.NEUTRAL


def _urgency(text: str) -> Urgency:
    if _CATALYST.search(text) and _URGENCY.search(text):
        return Urgency.HIGH
    if _URGENCY.search(text):
        return Urgency.MEDIUM
    return Urgency.LOW


def _conviction(
    text: str,
    signal_type: SignalType,
    tier: Optional[McapTier],
    caller_is_buying: bool,
    has_social_proof: bool,
    has_catalyst: bool,
) -> int:
    score = 5

    if signal_type == SignalType.FRESH_ENTRY:
        score += 1
    elif signal_type in (SignalType.HOLD_UPDATE, SignalType.PROGRESS_UPDATE):
        score -= 2

    if _VERY_BULLISH.search(text):
        score += 2
    elif _BULLISH.search(text):
        score += 1

    if _BEARISH.search(text):
        score -= 3

    if caller_is_buying:
        score += 2

    if has_social_proof:
        score += 1

    if has_catalyst:
        score += 1

    if _URGENCY.search(text):
        score += 1

    if text.count("!") >= 3:
        score += 1

    tier_bonus = {
        McapTier.ULTRA_EARLY: 2,
        McapTier.EARLY: 1,
        McapTier.MID: 0,
        McapTier.LATE: -1,
    }
    if tier:
        score += tier_bonus[tier]

    return max(1, min(10, score))


def _catalyst_hint(text: str) -> Optional[str]:
    m = _CATALYST.search(text)
    if not m:
        return None
    start = max(0, m.start() - 20)
    end = min(len(text), m.end() + 40)
    return text[start:end].strip().replace("\n", " ")


def parse_message(text: str, channel: str = "") -> Optional[ParsedSignal]:
    """
    Parse a Telegram message and return a ParsedSignal, or None if no
    valid CA + ticker can be extracted.
    """
    ca = _extract_ca(text)
    if not ca:
        return None

    ticker = _extract_ticker(text)
    if not ticker:
        return None

    sig_type       = _signal_type(text)
    entry_mcap     = _extract_entry_mcap(text)
    tier           = _mcap_tier(entry_mcap)
    target_mcap    = _extract_target_mcap(text)
    caller_buying  = bool(_CALLER_BUYING.search(text))
    social_proof   = bool(_SOCIAL_PROOF.search(text))
    has_catalyst   = bool(_CATALYST.search(text))

    conviction = _conviction(text, sig_type, tier, caller_buying, social_proof, has_catalyst)

    # Default TP/SL from tier; override TP2 if an explicit target mcap is stated
    tp1 = tp2 = sl = time_sl = None
    if tier:
        d = TIER_DEFAULTS[tier]
        tp1, tp2, sl, time_sl = d["tp1"], d["tp2"], d["sl"], d["time_sl_h"]

    # If caller gave a target mcap and we know entry mcap, convert to % gain for TP2
    if target_mcap and entry_mcap and entry_mcap > 0:
        implied_gain_pct = ((target_mcap - entry_mcap) / entry_mcap) * 100
        if implied_gain_pct > 0:
            tp2 = round(implied_gain_pct, 1)

    # Catalyst play: tighten time SL to 1h (pump immediately or not at all)
    if has_catalyst and _URGENCY.search(text) and time_sl:
        time_sl = 1.0

    return ParsedSignal(
        contract_address=ca,
        ticker=ticker,
        signal_type=sig_type,
        conviction=conviction,
        sentiment=_sentiment(text),
        urgency=_urgency(text),
        entry_mcap_usd=entry_mcap,
        entry_mcap_tier=tier,
        target_mcap_usd=target_mcap,
        tp1_pct=tp1,
        tp2_pct=tp2,
        sl_pct=sl,
        time_sl_hours=time_sl,
        has_catalyst=has_catalyst,
        catalyst_hint=_catalyst_hint(text),
        has_social_proof=social_proof,
        caller_is_buying=caller_buying,
        is_pump_fun=bool(_PUMP_FUN_CA.match(ca)),
        channel=channel,
        raw_text=text,
    )
