from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class DailyReportRequested:
    reason: str
    target_sessions: Optional[list[str]] = None
    requested_at: datetime = field(default_factory=datetime.now)
