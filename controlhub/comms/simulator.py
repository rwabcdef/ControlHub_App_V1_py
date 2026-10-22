"""Simulated motor for UI work without hardware (simulator.ts).

Sweeps the duty automatically, with a periodic step to show transients, and
reports samples at 1 kHz. It is not the hub: the CTRL0 / LIFT0 calls are absent,
so the UI reports "needs a serial or MQTT connection" for them. It still takes
the old placeholder commands as raw text:
    "DUTY <0-100>"  set PWM duty cycle (switches to manual)
    "STOP"          duty = 0 (manual)
    "AUTO"          resume the sweep
"""
from __future__ import annotations

import asyncio
import math
import random
import time

from ..types import RawSample
from .errors import CommsError
from .transport import TransportEvents

RATE_HZ = 1000
TICK_S = 0.010
MAX_RPM = 6000
TAU_S = 0.35  # mechanical time constant


class SimTransport:
    def __init__(self, ev: TransportEvents) -> None:
        self._ev = ev
        self._task: asyncio.Task | None = None
        self._sim_t = 0.0  # simulated time, s
        self._last_wall = 0.0
        self._rpm = 0.0
        self._duty = 0.0
        self._auto = True

    async def open(self) -> None:
        self._last_wall = time.perf_counter()
        self._task = asyncio.get_running_loop().create_task(self._run())

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def send(self, text: str) -> str | None:
        parts = text.strip().upper().split()
        cmd, arg = (parts + ["", ""])[:2]
        if cmd == "DUTY" and arg.replace(".", "", 1).isdigit():
            self._auto = False
            self._duty = min(100.0, max(0.0, float(arg)))
        elif cmd == "STOP":
            self._auto = False
            self._duty = 0.0
        elif cmd == "AUTO":
            self._auto = True
        else:
            raise CommsError(f'Simulator: unknown command "{text}"')
        return None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(TICK_S)
            self._tick()

    def _tick(self) -> None:
        now = time.perf_counter()
        n = int((now - self._last_wall) * RATE_HZ)
        self._last_wall += n / RATE_HZ
        dt = 1 / RATE_HZ
        for _ in range(n):
            self._sim_t += dt
            if self._auto:
                step = 0 if int(self._sim_t / 4) % 2 == 0 else 20
                self._duty = 35 + 25 * math.sin(2 * math.pi * self._sim_t / 12) + step
            target = self._duty / 100 * MAX_RPM
            accel = (target - self._rpm) / TAU_S  # rpm/s
            self._rpm += accel * dt
            current = 0.3 + 0.04 * self._duty + 0.0006 * accel + (random.random() - 0.5) * 0.15
            self._ev.sample(RawSample(rpm=self._rpm + (random.random() - 0.5) * 8, duty=self._duty,
                                      current=max(0.0, current), t=self._sim_t * 1000))
