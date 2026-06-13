"""
Run with:  python -m tests.test_parser
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from parser.regex_parser import parse_message
from parser.models import SignalType

EXAMPLES = [
    # ── Channel 1 ─────────────────────────────────────────────────────────────
    ("ch1_uswr_hold", "channel_1", """$USWR

-$USWR is looking good here for us, currently around the 8M market cap

-I'm still holding strong… much more to come…

FULL THESIS 👇🏻

https://www.instagram.com/reel/DZgFragvG3k/?igsh=dTNjcGgycnk3NHNv

Ca: 4D8qUHm334fxqeTauPvF8gQ7fYgrD4Mpmb1Wy6ftUSWR"""),

    ("ch1_aaif_update", "channel_1", """$AAIF (UPDATE)

-$AAIF is absolutely cooking for us!!

-Currently above the 5M market cap which is huge!

-We are going much, much higher…

FULL UPDATE 👇🏻

https://www.instagram.com/reel/DZdq4xpNevB/?igsh=MTVkb3NqanhpZ285cQ==

Ca: DyrxUUW9ZHYDo3JVyXX4DBGxQeyagWerbrrGT5KqAAiF"""),

    ("ch1_sipo_fresh", "channel_1", """$SIPO (2M)

-Grabbed a bag of $SIPO here around the 2M mc

Super early play here

This shit is about to send!!!

SipXamo8J1e6izV3iD2tMFcp1cBoVy8EXQFLd6JdxQd"""),

    ("ch1_uswr_ath", "channel_1", """$USWR (UPDATE)

-$USWR just smashed a new ATH, and it's looking like the green days are continuing…

-IMO, this is just the start..

-Much higher for $USWR

FULL THESIS 👇🏻

https://www.instagram.com/reel/DZa2-zXxCd5/?igsh=Z3F4a2ttcTR3c3pp

Ca: 4D8qUHm334fxqeTauPvF8gQ7fYgrD4Mpmb1Wy6ftUSWR"""),

    ("ch1_unit_fresh", "channel_1", """$UNIT (UNIFIED NETWORKED INTERNATIONAL TOKEN)

-Grabbed a bag of $UNIT here around the 1.5M range…

-$UNIT is the decentralized financial arm in BRICS, with objectives in building the new world financial order.

-narrative is super bullish here, and team has ran multiple projects to the 10s of millions…

-personally I'm apeing a decent sized bag, as I think this should cool for us…

FULL THESIS 👇

https://www.instagram.com/reel/DYF-gXzvYOp/?igsh=MTFma2tmZHEzZ3pqMA==

Ca: unitqNfP9rvX5FXoyg3RQ5YDXdAVF3ELfNFeqPktnin"""),

    ("ch1_usem_fresh", "channel_1", """$USEM (2.5M)

(United States equalizer movement)

-Grabbing some $USEM around these 2.5M range here…

-I've been eyeing down this project for a while now, and I think this is a perfect time to show it to you guys…

-there are rumours going around that this is the mayor of NYC's coin

-Narrative is insane, this should cook for us..

FULL THESIS 👇🏻

https://www.instagram.com/reel/DYFDCQgOSEW/?igsh=dThuenEzdzF0OTNh

Ca: usemtUxHat32zmoyLicWbiLXxnYi2eoELbHGE6Nugpj"""),

    # ── Channel 2 ─────────────────────────────────────────────────────────────
    ("ch2_manifest_fresh", "channel_2", """Buying some $MANIFEST here at 30m

Lowcap memes haven't been the best recently in this market - parking size in mid/high caps seems to be the move

$MANIFEST has been holding an incredible chart for a while now.

Been seeing some chads push it too, I am bullish, break it out.

BCdwQBAn8dYB5YjTsoB6TdHAWokxv28k2oZUodERpump

https://dexscreener.com/solana/2DVbU5h8JCd37gaXAJUZ4t77HsjJW22LLduTZk7GSa43"""),

    ("ch2_match_catalyst", "channel_2", """Aping some $MATCH here at 800k

Token has been holding up well ans the world cup starts in few hours.

$MATCH is one of the few tokens with a real-world catalyst happening right now.

Every match creates new users, new predictions, new engagement, and new prize pools.

CvPrreLgpZ9tjjoyk8qAwiAFvuEXooU7wL25hanApump

https://dexscreener.com/solana/gc5npgagnwzonkjkurqmlmxyybjzirraw7ffn6jjnwe8"""),

    ("ch2_manifest_update", "channel_2", """$MANIFEST is moving very well here for a high cap

Volume is nice and the team is cooking - Ansem is liking $MANIFEST related tweets too

Lets see this break above 50m

https://dexscreener.com/solana/2DVbU5h8JCd37gaXAJUZ4t77HsjJW22LLduTZk7GSa43"""),
]


def fmt_usd(v: float | None) -> str:
    if v is None:
        return "—"
    if v >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v/1_000:.0f}K"
    return f"${v:.0f}"


def fmt_pct(v: float | None) -> str:
    return f"{v:+.0f}%" if v is not None else "—"


if __name__ == "__main__":
    passed = 0
    failed = 0

    for name, channel, text in EXAMPLES:
        result = parse_message(text, channel)
        print(f"\n{'─'*65}")
        print(f"  {name}  [{channel}]")
        print(f"{'─'*65}")

        if result is None:
            # ch2_manifest_update has no CA — expected None
            if "update" in name and channel == "channel_2":
                print("  → None (expected: update message has no CA)")
                passed += 1
            else:
                print("  → PARSE FAILED — returned None unexpectedly")
                failed += 1
            continue

        passed += 1
        buy_signal = result.signal_type == SignalType.FRESH_ENTRY
        action = "BUY SIGNAL" if buy_signal else "skip (not fresh entry)"

        print(f"  Ticker:       ${result.ticker}")
        print(f"  CA:           {result.contract_address[:16]}...")
        print(f"  Type:         {result.signal_type.value}  →  {action}")
        print(f"  Conviction:   {result.conviction}/10")
        print(f"  Sentiment:    {result.sentiment.value}")
        print(f"  Urgency:      {result.urgency.value}")
        print(f"  Entry mcap:   {fmt_usd(result.entry_mcap_usd)}  ({result.entry_mcap_tier.value if result.entry_mcap_tier else '—'})")
        print(f"  Target mcap:  {fmt_usd(result.target_mcap_usd)}")
        print(f"  TP1 / TP2:    {fmt_pct(result.tp1_pct)} / {fmt_pct(result.tp2_pct)}")
        print(f"  SL:           {fmt_pct(result.sl_pct)}   time SL: {result.time_sl_hours}h")
        print(f"  Caller buys:  {result.caller_is_buying}   Social proof: {result.has_social_proof}   Catalyst: {result.has_catalyst}")
        if result.catalyst_hint:
            print(f"  Catalyst:     {result.catalyst_hint[:60]}")
        print(f"  Pump.fun:     {result.is_pump_fun}")

    print(f"\n{'='*65}")
    print(f"  Results: {passed} passed, {failed} failed")
    print(f"{'='*65}\n")
