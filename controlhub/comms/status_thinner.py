"""Thins the hub's CTRL0 status frames out of a log (statusThinner.ts)."""
from __future__ import annotations

import re

_STATUS_FRAME = re.compile(r"CTRL0U\d{6}([ICL])[FR]\d{3}\.\d{4}\.\d{4}")
"""The status frame anywhere in a line, e.g. CTRL0U001020CF030.0350.1234.0150 as it
arrives on MQTT, or "rx CTRL0U001020CF030..." in the SerLink trace. Group 1 is the
mode: I idle, C control, L lift."""

STATUS_KEEP_EVERY = 10
"""Keep one status frame in this many while the hub runs"""


class StatusThinner:
    """The frames come 4 times a second while the hub runs, and would bury everything
    else in the MQTT log and the SerLink trace. Of a run's frames (mode C or L) the
    1st, 11th, 21st... are kept; the Idle frame the hub sends once when the run stops
    is always kept, and starts the count again. Every other line is kept. Telemetry
    is not affected - this is for logs only. One instance per log."""

    def __init__(self) -> None:
        self._count = 0

    def keep(self, line: str) -> bool:
        m = _STATUS_FRAME.search(line)
        if not m:
            return True
        if m[1] == "I":
            self._count = 0
            return True
        keep = self._count % STATUS_KEEP_EVERY == 0
        self._count += 1
        return keep
