"""High-rate telemetry buffer, kept OUTSIDE widget state (telemetry/store.ts).

Samples arrive at up to 1 kHz (the simulator) or 4 Hz (the hub's status frames).
Widgets never get a signal per sample: one 60 Hz timer (ui/frame_clock.py) asks
`version` whether anything new arrived, and the gauges and charts redraw from
these arrays only then.
"""
from __future__ import annotations

import time

import numpy as np

from ..types import MotorField

MAX_POINTS = 60_000
"""Keep up to this many samples (e.g. 60 s at 1 kHz)."""
_CAPACITY = MAX_POINTS + MAX_POINTS // 4


class TelemetryStore:
    def __init__(self) -> None:
        # Columnar arrays, time in seconds; NaN where the source didn't report the value (drawn as a gap)
        self._cols = {k: np.empty(_CAPACITY) for k in ("t", "rpm", "duty", "current")}
        self._n = 0
        self.latest: dict[str, float] | None = None
        """The newest sample: t (ms), rpm, duty, current"""
        self.rate = 0.0
        """Measured incoming sample rate, Hz"""
        self.version = 0
        """Bumped on every push / clear; redraw when it differs from the last one drawn"""
        self._rate_count = 0
        self._rate_since = time.perf_counter()

    def push(self, t_ms: float, rpm: float, duty: float, current: float) -> None:
        if self._n == _CAPACITY:
            # Trim in chunks so the O(n) shift is amortised.
            excess = self._n - MAX_POINTS
            for a in self._cols.values():
                a[:MAX_POINTS] = a[excess:self._n]
            self._n = MAX_POINTS
        i = self._n
        c = self._cols
        c["t"][i], c["rpm"][i], c["duty"][i], c["current"][i] = t_ms / 1000, rpm, duty, current
        self._n += 1
        self.latest = {"t": t_ms, "rpm": rpm, "duty": duty, "current": current}
        self._rate_count += 1
        now = time.perf_counter()
        if now - self._rate_since >= 1.0:
            self.rate = self._rate_count / (now - self._rate_since)
            self._rate_count = 0
            self._rate_since = now
        self.version += 1

    def clear(self) -> None:
        self._n = 0
        self.latest = None
        self.rate = 0.0
        self._rate_count = 0
        self._rate_since = time.perf_counter()
        self.version += 1

    def __len__(self) -> int:
        return self._n

    @property
    def t(self) -> np.ndarray:
        """Sample times, s (a view; valid until the next push)"""
        return self._cols["t"][: self._n]

    def series(self, field: MotorField) -> np.ndarray:
        return self._cols[field][: self._n]


telemetry = TelemetryStore()
"""The app's telemetry buffer (one per process)."""
