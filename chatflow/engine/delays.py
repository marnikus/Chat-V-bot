"""Human-like delay math (pure, no asyncio)."""
from __future__ import annotations

import random

MIN_DELAY_FLOOR = 0.2


def jittered(base: float, jitter: float,
             rng: random.Random | None = None, floor: float = MIN_DELAY_FLOOR) -> float:
    """base ± uniform jitter; zero stays zero (explicit no-delay)."""
    r = rng or random
    if not base:
        return 0.0
    value = base + (r.uniform(-jitter, jitter) if jitter else 0.0)
    return max(value, floor)


def char_delay(cps: float, variance_pct: float,
               rng: random.Random | None = None) -> float:
    """Per-character typing delay with gaussian variance."""
    r = rng or random
    base = 1.0 / max(cps, 1.0)
    return max(base * (1.0 + r.gauss(0.0, max(variance_pct, 0.0) / 100.0)), 0.01)


def wheel_chunks(total: int, lo: int = 40, hi: int = 120,
                 rng: random.Random | None = None) -> list[int]:
    """Split a wheel delta into 3-7 human-like ticks."""
    r = rng or random
    total = int(total)
    if total == 0:
        return []
    n = r.randint(3, 7) if abs(total) > 150 else r.randint(2, 4)
    sign = 1 if total > 0 else -1
    chunks = [max(lo // 2, r.randint(lo, hi)) for _ in range(n)]
    while sum(chunks) < abs(total):
        chunks[r.randrange(len(chunks))] += lo
    out, left = [], abs(total)
    for c in chunks:
        take = min(c, left)
        if take:
            out.append(sign * take)
        left -= take
        if not left:
            break
    return out or [sign * min(abs(total), hi)]
