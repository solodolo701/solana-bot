import re
import time
from dataclasses import dataclass

_CA_PATTERN = re.compile(r'[1-9A-HJ-NP-Za-km-z]{32,44}')


@dataclass
class FilterResult:
    should_process: bool
    reason: str


class MessageFilter:
    """Pre-LLM gate: checks a CA exists and deduplicates within a TTL window."""

    def __init__(self, dedup_ttl_seconds: int = 1800):
        self._seen: dict[str, float] = {}
        self._ttl = dedup_ttl_seconds

    def filter(self, text: str) -> FilterResult:
        if not _CA_PATTERN.search(text):
            return FilterResult(False, "no_ca_found")

        now = time.time()
        self._seen = {ca: ts for ca, ts in self._seen.items() if now - ts < self._ttl}

        for ca in _CA_PATTERN.findall(text):
            if ca in self._seen:
                return FilterResult(False, f"duplicate:{ca[:8]}")

        for ca in _CA_PATTERN.findall(text):
            self._seen[ca] = now

        return FilterResult(True, "ok")

    def mark_seen(self, ca: str) -> None:
        self._seen[ca] = time.time()

    def clear(self) -> None:
        self._seen.clear()
