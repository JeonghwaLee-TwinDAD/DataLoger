"""
models.py
---------
Shared data model and queue-protocol constants used between acquisition,
processing, logging, and the dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

# Event-queue command tokens (dashboard event loop)
CMD_START = "START"
CMD_STOP  = "STOP"
CMD_EXIT  = "EXIT"

# Remote-control command token (dispatched to the UI thread via _remote_cmd_queue)
REMOTE_CMD_TOGGLE_RECORD = "TOGGLE_RECORD"

# Series identifiers
SID_TIME = "Time"
SID_FLOW = "Flow"

DataPoint = Tuple[str, float, float]


@dataclass
class Series:
    """A typed data container holding two parallel lists of floats (xs, ys)."""

    name: str
    xs: List[float] = field(default_factory=list)
    ys: List[float] = field(default_factory=list)

    def append(self, x: float, y: float) -> None:
        self.xs.append(x)
        self.ys.append(y)

    def clear(self) -> None:
        self.xs.clear()
        self.ys.clear()

    def snapshot(self) -> "Series":
        """Return a copy of this Series, safe to hand to another thread."""
        return Series(name=self.name, xs=list(self.xs), ys=list(self.ys))
