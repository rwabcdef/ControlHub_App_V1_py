"""Shared test helpers: run a coroutine, a recording link, and a fake hub that answers
CTRL0 / MOTOR / LIFT0 as the firmware does (main_tasks.cpp)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from controlhub.comms.serlink import serlink as serlink_mod  # noqa: E402
from controlhub.comms.serlink.frame import Frame  # noqa: E402
from controlhub.comms.transport import TransportEvents  # noqa: E402


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def fast_timeouts(monkeypatch):
    """Ack timeouts of 1 s / 2 s would make every timeout test slow."""
    monkeypatch.setattr(serlink_mod, "ACK_TIMEOUT_MS", 50)
    monkeypatch.setattr(serlink_mod, "RELAY_ACK_TIMEOUT_MS", 80)


class Recorder:
    """A LineWriter that records each line; `respond` (if set) answers a line by
    returning lines to feed back into `target` (on the next loop turn, as a link would)."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.target = None  # .receive_line(str)
        self.respond = None  # Callable[[str], list[str]]
        self.fail: Exception | None = None

    async def __call__(self, line: str) -> None:
        if self.fail is not None:
            raise self.fail
        self.lines.append(line)
        if self.respond is not None and self.target is not None:
            for answer in self.respond(line):
                asyncio.get_running_loop().call_soon(self.target.receive_line, answer)


class Events:
    """A TransportEvents that records everything."""

    def __init__(self) -> None:
        self.samples, self.lifts, self.hubs, self.errors = [], [], [], []
        self.ev = TransportEvents(sample=self.samples.append, lift=self.lifts.append, hub=self.hubs.append,
                                  error=self.errors.append, reconnected=lambda: None, close=lambda: None)


class FakeHub:
    """Answers CTRL0 'T' frames like HubApp / the CTRL0 handlers in main_tasks.cpp."""

    def __init__(self) -> None:
        self.gain_micro = 2000
        self.rpm = 150
        self.measured = 148
        self.max_duty = 50
        self.direction = "F"
        self.mode = "I"
        self.source = "-"
        self.motor_duty = 0
        self.motor_direction = "D"
        self.clock: str | None = None
        """RTC00: the last yyyymmddhhmmss taken; None until set"""
        self.clock_reply: str | None = None
        """RTC00 G's answer, e.g. G120261023143007; None = a plain ACK_OK"""
        self.received: list[Frame] = []

    def __call__(self, line: str) -> list[str]:
        f = Frame.from_string(line)
        if f is None or f.type not in ("T", "S"):
            if f is not None:
                self.received.append(f)
            return []
        self.received.append(f)
        if f.type == "S":
            return [str(Frame(f.protocol, "A", f.roll_code, 8, "PINGBACK"))] if f.protocol in ("CTRL0", "LIFT0") \
                else [str(Frame(f.protocol, "A", f.roll_code, Frame.ACK_OK))]
        reply = self.handle_motor(f.data) if f.protocol == "MOTOR" else \
            self.handle_rtc(f.data) if f.protocol == "RTC00" else self.handle(f.data)
        if reply is None:
            return [str(Frame(f.protocol, "A", f.roll_code, Frame.ACK_OK))]
        return [str(Frame(f.protocol, "A", f.roll_code, len(reply), reply))]

    def handle_motor(self, data: str) -> str | None:
        """motorSockReceiveHandler / motorSockInstantHandler: P and D only while idle.
        Both selectors reach the one motor, as on the hub."""
        cmd = data[1:]
        if cmd == "GP":
            return f"{self.motor_duty:03d}"
        if cmd == "GD":
            return self.motor_direction
        if self.mode == "I":
            if cmd[:1] == "P" and len(cmd) == 4:
                self.motor_duty = min(100, int(cmd[1:]))
            elif cmd in ("DF", "DR", "DD"):
                self.motor_direction = cmd[1]
        return None

    def handle_rtc(self, data: str) -> str | None:
        """rtcSockInstantHandler: S<yyyymmddhhmmss> answered S1 / S0 on the ack, G with clock_reply."""
        if data == "G":
            return self.clock_reply
        if data[:1] != "S":
            return None
        ok = len(data) == 15 and data[1:].isdigit() and 2000 <= int(data[1:5]) <= 2099
        if ok:
            self.clock = data[1:]
        return "S1" if ok else "S0"

    def handle(self, data: str) -> str | None:
        if data == "BGA":
            return f"{self.gain_micro:06d}.{self.rpm:04d}.{self.measured:04d}"
        if data == "BGM":
            return f"{self.max_duty:03d}"
        if data == "BGD":
            return self.direction
        if data == "BGO":
            return self.mode + self.source
        if data == "BGI":
            return f"{self.gain_micro:06d}"
        if data == "BGR":
            return f"{self.rpm:04d}"
        if data.startswith("BI"):
            self.gain_micro = int(data[2:])
        elif data.startswith("BR"):
            if self.mode != "L":  # refused during a lift move
                self.rpm = int(data[2:])
        elif data.startswith("BM"):
            if 20 <= int(data[2:]) <= 100:
                self.max_duty = int(data[2:])
        elif data in ("BDF", "BDR"):
            if self.mode == "I":
                self.direction = data[2]
        return None
