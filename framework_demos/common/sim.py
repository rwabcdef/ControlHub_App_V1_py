"""A fake hub for the framework demos: telemetry, HubApp's modes and the
Dashboard -> Control panel's rules, with no hub, serial port or MQTT.

Framework-agnostic and single-threaded: each demo calls step() from its own
UI timer (or frame callback), and reads the state it needs. All of the
"why is this disabled" logic from DashboardControl.tsx lives here, so each
demo is only presentation, and the demos can't drift apart on behaviour.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

import numpy as np

# Demo scales (the app's own defaults are rpmMax 6000 / currentMax 5 / dialRpmMax 300;
# the gauge max is lowered so the needle moves visibly at dial speeds)
RPM_MAX = 600.0
CURRENT_MAX = 5.0
DIAL_RPM_MAX = 300
WINDOW_SEC = 10.0
SAMPLE_HZ = 50.0
LIFT_DISTANCE = 100  # edges
BUSY_S = 0.3

SCENARIOS = ["Live (use the buttons)", "Idle", "Control · PC", "Control · Remote", "Lift"]


@dataclass
class DialView:
    value: int | None
    #: 'edit', 'readonly' (a meter: full colour, inert) or 'disabled' (greyed)
    state: str
    tooltip: str


class HubSim:
    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self.mode = "idle"  # idle | control | lift
        self.source = "none"  # pc | remote | none
        self.direction = "forward"
        self.pc_rpm = 120  # the hub's target (BR), what the dial edits
        self.pot_rpm = 0
        self.rpm = 0.0
        self.duty = 0.0
        self.current = 0.15
        self.lift_travelled = 0.0
        self.lift_target = 0
        self.done = False
        self.move_mode = "upDown"  # upDown | forRev
        self.lift_direction = "forward"
        self.busy: str | None = None
        self._busy_until = 0.0
        self._busy_action = None
        self.scenario = SCENARIOS[0]
        # History ring for the strip charts
        n = int(WINDOW_SEC * SAMPLE_HZ * 3)
        self._t = np.zeros(n)
        self._y = {k: np.zeros(n) for k in ("rpm", "duty", "current")}
        self._n = 0
        self._last = 0.0
        self._acc = 0.0

    # ---- time -----------------------------------------------------------
    def now(self) -> float:
        return time.perf_counter() - self.t0

    def step(self) -> None:
        """Advance to now, in fixed 1/SAMPLE_HZ steps (call it as often as you like)."""
        now = self.now()
        self._acc += now - self._last
        self._last = now
        dt = 1.0 / SAMPLE_HZ
        while self._acc >= dt:
            self._acc -= dt
            self._tick(now - self._acc, dt)
        if self.busy and now >= self._busy_until:
            action, self._busy_action, self.busy = self._busy_action, None, None
            if action:
                action()

    def _tick(self, t: float, dt: float) -> None:
        if self.mode == "control" and self.source == "remote":
            # The remote's pot, being turned slowly
            self.pot_rpm = int(150 + 120 * math.sin(t * 0.4))
        running = self.mode != "idle"
        target = self.run_rpm() if running else 0
        self.rpm += (target - self.rpm) * min(1.0, dt / 0.6)
        noise = random.gauss(0, 2.0) if running else 0.0
        self.duty = max(0.0, min(100.0, self.rpm / RPM_MAX * 70 + (random.gauss(0, 0.6) if running else 0)))
        self.current = max(0.0, 0.15 + self.duty * 0.03 + (random.gauss(0, 0.03) if running else 0))
        if self.mode == "lift":
            self.lift_travelled += self.rpm / 60 * 2 * dt
            if self.lift_travelled >= self.lift_target:
                self.lift_travelled = self.lift_target
                self._enter_idle()
                self.done = True
        self._push(t, max(0.0, self.rpm + noise), self.duty, self.current)

    def _push(self, t: float, rpm: float, duty: float, current: float) -> None:
        n = len(self._t)
        if self._n == n:  # shift left by a third, rarely
            k = n // 3
            self._t[:-k] = self._t[k:]
            for a in self._y.values():
                a[:-k] = a[k:]
            self._n -= k
        i = self._n
        self._t[i] = t
        self._y["rpm"][i] = rpm
        self._y["duty"][i] = duty
        self._y["current"][i] = current
        self._n += 1

    def history(self, field: str) -> tuple[np.ndarray, np.ndarray]:
        """Views (no copy) of the samples so far: t (s) and the field."""
        return self._t[: self._n], self._y[field][: self._n]

    def latest(self, field: str) -> float | None:
        return float(self._y[field][self._n - 1]) if self._n else None

    # ---- hub rules (HubApp) -----------------------------------------------
    def run_rpm(self) -> int:
        return self.pot_rpm if self.source == "remote" else self.pc_rpm

    def _enter_idle(self) -> None:
        self.mode, self.source = "idle", "none"

    def _start_control(self, source: str) -> None:
        if self.mode == "idle":
            self.mode, self.source = "control", source
            if source == "remote":
                self.pot_rpm = int(150 + 120 * math.sin(self.now() * 0.4))

    def _start_lift(self, distance: int, direction: str) -> None:
        if self.mode == "idle" and self.pc_rpm > 0:
            self.direction = direction
            self.mode, self.source = "lift", "pc"
            self.lift_travelled, self.lift_target, self.done = 0.0, distance, False

    def _busy(self, which: str, action) -> None:
        if self.busy:
            return
        self.busy, self._busy_action, self._busy_until = which, action, self.now() + BUSY_S

    # ---- what the Control panel's buttons do -------------------------------
    def start(self) -> None:
        self._busy("start", lambda: self._start_control("pc"))

    def stop(self) -> None:
        self._busy("stop", self._stop_now)

    def _stop_now(self) -> None:
        # A stopped lift move still ends with the hub's done frame
        was_lift = self.mode == "lift"
        self._enter_idle()
        if was_lift:
            self.done = True

    def set_direction(self, d: str) -> None:
        self._busy("direction", lambda: setattr(self, "direction", d) if self.mode == "idle" else None)

    def lift_up(self) -> None:
        self._busy("up", lambda: self._start_lift(LIFT_DISTANCE, "forward"))

    def lift_down(self) -> None:
        self._busy("down", lambda: self._start_lift(self.down_max(), "reverse"))

    def lift_move(self) -> None:
        self._busy("move", lambda: self._start_lift(LIFT_DISTANCE, self.lift_direction))

    def set_rpm(self, v: int) -> None:
        """The dial, as it turns (setRpmLive): live in a PC run, the next run's while Idle."""
        if self.mode != "lift":
            self.pc_rpm = int(v)

    def remote_button(self) -> None:
        """The remote's button 1: start a remote run if Idle, else stop."""
        if self.mode == "idle":
            self._start_control("remote")
        else:
            self._enter_idle()

    def set_scenario(self, name: str) -> None:
        self.scenario = name
        self.busy = None
        if name == "Idle":
            self._enter_idle()
        elif name == "Control · PC":
            self._enter_idle()
            self._start_control("pc")
        elif name == "Control · Remote":
            self._enter_idle()
            self._start_control("remote")
        elif name == "Lift":
            self._enter_idle()
            self._start_lift(LIFT_DISTANCE * 3, "forward")

    # ---- the view logic of DashboardControl.tsx ----------------------------
    @staticmethod
    def down_max() -> int:
        return math.ceil(LIFT_DISTANCE * 1.2)

    def start_blocked(self) -> str:
        return "" if self.mode == "idle" else "The hub is running - stop it first"

    def lift_blocked(self) -> str:
        return self.start_blocked() or ("The target speed is 0 - turn the dial up first" if self.pc_rpm == 0 else "")

    def dial(self) -> DialView:
        if self.mode == "control" and self.source == "remote":
            return DialView(self.pot_rpm, "readonly", "The remote's pot sets this run's speed")
        if self.mode == "lift":
            return DialView(self.pc_rpm, "disabled", "The speed is fixed during a lift move")
        return DialView(self.pc_rpm, "edit", "")

    def mode_chip(self) -> tuple[str, str]:
        """(label, colour role: default | success | info)"""
        label = {"idle": "Idle", "control": "Control", "lift": "Lift"}[self.mode]
        src = {"pc": "PC", "remote": "Remote", "none": ""}[self.source]
        role = {"idle": "default", "control": "success", "lift": "info"}[self.mode]
        return (f"{label} · {src}" if src else label), role

    def lift_caption(self) -> str:
        extra = f" (Down: {self.down_max()} max)" if self.move_mode == "upDown" else ""
        return f"{LIFT_DISTANCE} edges{extra}"

    def lift_progress(self) -> str:
        if self.mode == "lift" or self.done:
            return f"{int(self.lift_travelled)} / {self.lift_target} edges"
        return ""


class FpsMeter:
    """Frames per second and mean frame time over the last second."""

    def __init__(self) -> None:
        self._times: list[float] = []

    def frame(self) -> None:
        now = time.perf_counter()
        self._times.append(now)
        while self._times and now - self._times[0] > 1.0:
            self._times.pop(0)

    def text(self) -> str:
        n = len(self._times)
        if n < 2:
            return "— fps"
        span = self._times[-1] - self._times[0]
        return f"{(n - 1) / span:.0f} fps · {span / (n - 1) * 1000:.1f} ms"
