"""MQTT traffic log, both directions (state/mqttLog.ts).

Kept outside widget state like the telemetry buffer: lines can arrive in bursts, and
redrawing the log page per line would be wasteful. Listeners are told at most every
NOTIFY_MS instead, and read a snapshot. Collected from app start, whichever page is
showing, so the log page shows what happened before it was opened.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from ..types import MqttLogLine

MAX_LINES = 5_000
"""Lines kept; the oldest go first."""
NOTIFY_MS = 200
"""The page redraws at most this often, however fast lines arrive."""


class MqttLogStore(QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._lines: list[MqttLogLine] = []
        self.snapshot: list[MqttLogLine] = []
        """What the page shows (frozen while paused)"""
        self._paused = False
        """While paused, lines are still collected but the snapshot is frozen."""
        self._timer = QTimer(self, singleShot=True, interval=NOTIFY_MS, timeout=self._publish)

    def push(self, line: MqttLogLine) -> None:
        self._lines.append(line)
        if len(self._lines) > MAX_LINES + MAX_LINES // 10:  # trim in chunks
            del self._lines[: len(self._lines) - MAX_LINES]
        self._schedule()

    def clear(self) -> None:
        self._lines = []
        self.snapshot = []
        self.changed.emit()

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if not paused:
            self._schedule()

    def _schedule(self) -> None:
        if not self._paused and not self._timer.isActive():
            self._timer.start()

    def _publish(self) -> None:
        if not self._paused:
            self.snapshot = self._lines[-MAX_LINES:]
            self.changed.emit()
