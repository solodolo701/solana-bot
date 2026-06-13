import asyncio
import functools
from typing import TypeVar, Callable

T = TypeVar("T")


def retry(max_attempts: int = 3, base_delay: float = 1.0):
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    delay = base_delay * (2 ** attempt)
                    await asyncio.sleep(delay)
        return wrapper
    return decorator


def lamports_to_sol(lamports: int) -> float:
    return lamports / 1_000_000_000


def sol_to_lamports(sol: float) -> int:
    return int(sol * 1_000_000_000)


def short_address(address: str) -> str:
    return f"{address[:4]}...{address[-4:]}"


def parse_mcap_string(mcap_str: str) -> float | None:
    """Convert '30m', '800k', '1.5M' → float in USD."""
    if not mcap_str:
        return None
    cleaned = mcap_str.strip().upper()
    multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    for suffix, mult in multipliers.items():
        if cleaned.endswith(suffix):
            try:
                return float(cleaned[:-1]) * mult
            except ValueError:
                return None
    try:
        return float(cleaned)
    except ValueError:
        return None
