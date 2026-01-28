from __future__ import annotations

import re
from typing import Optional

_SUFFIX = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
_CN_SUFFIX = {"万": 10_000, "w": 10_000, "亿": 100_000_000}


def parse_compact_int(value: str | None) -> Optional[int]:
    if not value:
        return None

    s = str(value).strip()
    if not s:
        return None

    # Common noise
    s = re.sub(r"(?i)\bviews?\b", "", s)
    s = s.replace("观看", "").replace("次观看", "").replace("播放", "")
    s = s.replace(",", "").replace(" ", "")

    # Percent is not a count.
    if s.endswith("%"):
        return None

    # 1.2K / 3M / 10B
    m = re.fullmatch(r"(?i)(\d+(?:\.\d+)?)([kmb])?", s)
    if m:
        num = float(m.group(1))
        suffix = m.group(2).lower() if m.group(2) else ""
        mult = _SUFFIX.get(suffix, 1)
        return int(num * mult)

    # 1.2万 / 3亿 / 1.2w
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(万|亿|w)", s, flags=re.IGNORECASE)
    if m:
        num = float(m.group(1))
        mult = _CN_SUFFIX.get(m.group(2).lower(), 1)
        return int(num * mult)

    # Fallback: first integer in string
    m = re.search(r"(\d+)", s)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def parse_percent_int(value: str | None) -> Optional[int]:
    if not value:
        return None
    s = str(value).strip()
    m = re.search(r"(\d{1,3})\s*%", s)
    if not m:
        return None
    try:
        v = int(m.group(1))
    except Exception:
        return None
    return max(0, min(100, v))
