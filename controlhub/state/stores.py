"""The app's low-rate state, as small QObjects with a `changed` signal - the Electron app's
zustand stores (state/*.ts), with the same rules. High-rate data is not here: see
telemetry.py and mqtt_log.py.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from PySide6.QtCore import QObject, Signal

from ..asyncutil import spawn
from ..comms.hub import CommsHub
from ..settings import settings
from ..types import (CTRL_RPM_MAX, LIFT_DISTANCE_MAX, MOTORS_FITTED, CommsState, ControlHubSettings, CtrlDirection,
                     CtrlSettings, DisplaySettings, HubState, LiftDirection, LiftStatus, MotorDirection, MotorId,
                     PingReport)


# --------------------------------------------------------------------------- hub
class HubStore(QObject):
    """The hub's state (HubApp in the firmware): idle, a Control run or a lift move.
    None until known (read on connecting, then each status frame)."""

    changed = Signal()

    def __init__(self, comms: CommsHub) -> None:
        super().__init__()
        self.hub: HubState | None = None
        comms.hub_state.connect(self.set)
        # Forget it when the link goes; CtrlStore reads it again on connecting.
        comms.state_changed.connect(lambda s: s.status != "connected" and self.set(None))

    def set(self, hub: HubState | None) -> None:
        if hub != self.hub:
            self.hub = hub
            self.changed.emit()


# --------------------------------------------------------------------------- ctrl
CtrlMode = Literal["integral", "proportional", "integralProportional"]


@dataclass(frozen=True)
class RpmError:
    """Why the last set_rpm_live() failed. A new object per failure (identity, not
    equality, matters), so the same message twice still reads as a new failure."""

    message: str

    def __eq__(self, other: object) -> bool:
        return self is other

    __hash__ = object.__hash__


class CtrlStore(QObject):
    """Speed controller B's settings, and Control runs, through the hub's CTRL0 socket
    (state/ctrl.ts). Values are what the hub holds, as last read (BGA, BGM) or saved;
    None until known."""

    changed = Signal()

    def __init__(self, comms: CommsHub, hub: HubStore) -> None:
        super().__init__()
        self._comms = comms
        self._hub = hub
        self.mode: CtrlMode = "integral"
        self.gain_i: float | None = None
        self.rpm: int | None = None
        """The hub's target speed: the next run's, and a PC Control run's in progress"""
        self.rpm_error: RpmError | None = None
        self.max_duty: int | None = None
        self.loading = False
        self.load_error: str | None = None
        # set_rpm_live()'s coalescing: the value still to send, and whether a send is running
        self._pending_rpm: int | None = None
        self._rpm_in_flight = False
        comms.state_changed.connect(self._apply)

    def _set(self, **kw) -> None:
        for k, v in kw.items():
            setattr(self, k, v)
        self.changed.emit()

    def set_mode(self, mode: CtrlMode) -> None:
        self._set(mode=mode)

    async def load(self) -> None:
        """Read the hub's values (BGA, BGM, BGD, BGO) - and its state, into HubStore."""
        self._set(loading=True, load_error=None)
        try:
            r = await self._comms.ctrl_get()
            self._set(gain_i=r.gain_i, rpm=r.rpm, max_duty=r.max_duty)
            self._hub.set(r.hub)
        except Exception as e:  # noqa: BLE001
            self._set(load_error=str(e))
        finally:
            self._set(loading=False)

    async def save(self, s: CtrlSettings) -> None:
        """Send the changed values; raises if the hub doesn't take them."""
        saved = await self._comms.ctrl_set(s)
        # A set that finishes after a disconnect must not bring back values _apply() has forgotten.
        if self.rpm is None and self.gain_i is None and self.max_duty is None:
            return
        self._set(gain_i=saved.gain_i if saved.gain_i is not None else self.gain_i,
                  rpm=saved.rpm if saved.rpm is not None else self.rpm,
                  max_duty=saved.max_duty if saved.max_duty is not None else self.max_duty)

    def set_rpm_live(self, rpm: int) -> None:
        """The dashboard dial: set the target speed as it turns. Never raises - a failure
        lands in rpm_error. One set is in flight at a time; values given meanwhile replace
        each other, and only the latest is sent next."""
        self._pending_rpm = rpm
        if self._rpm_in_flight:
            return
        self._rpm_in_flight = True
        spawn(self._send_rpm())

    async def _send_rpm(self) -> None:
        try:
            while self._pending_rpm is not None:
                nxt, self._pending_rpm = self._pending_rpm, None
                try:
                    await self.save(CtrlSettings(rpm=nxt))
                    self._set(rpm_error=None)
                except Exception as e:  # noqa: BLE001
                    # Dropped if the link went in the meantime - a reconnect starts clean.
                    if self._pending_rpm is None and self.rpm is not None:
                        self._set(rpm_error=RpmError(str(e)))
        finally:
            self._rpm_in_flight = False

    async def start(self) -> None:
        """Start a Control run (BS) - ignored by the hub unless idle"""
        await self._comms.ctrl_start()

    async def stop(self) -> None:
        """Stop whatever runs - a Control run or a lift move (BX)"""
        await self._comms.ctrl_stop()

    async def set_direction(self, direction: CtrlDirection) -> None:
        """Select the direction (BD) - ignored by the hub unless idle"""
        await self._comms.ctrl_set_direction(direction)
        # The hub only says so in its next status frame, which only comes while running -
        # read it back now, so the selection shows straight away.
        await self.load()

    def _apply(self, s: CommsState) -> None:
        """Read the hub's values on each (re)connection to it; forget them when disconnected."""
        if s.status == "connected" and s.kind != "sim":
            self._set(rpm_error=None)
            spawn(self.load())
        elif s.status in ("connecting", "disconnected", "error"):
            self._pending_rpm = None
            self._set(gain_i=None, rpm=None, rpm_error=None, max_duty=None, load_error=None)


# --------------------------------------------------------------------------- direct
@dataclass
class DirectMotor:
    """One motor on the Direct page: what the hub holds, as last read (GP, GD) or set;
    None until known."""

    duty: int | None = None
    requested: int | None = None
    """The duty last asked for - the dial's latest value (or Stop's 0), ahead of the hub
    while a set is on its way; the hub's duty again after a read"""
    direction: MotorDirection | None = None
    duty_error: RpmError | None = None
    """Why the last set_duty_live() failed (a new object per failure, as rpm_error);
    cleared by the next one that succeeds"""
    dial_reset: object | None = None
    """A new object on each Stop. Passed to the dial as its error (with duty_error), so it
    drops a value of its own that was never sent and shows the hub's."""
    error: str | None = None
    """Why the last read or direction set failed"""


class DirectStore(QObject):
    """Direct motor control, through the hub's MOTOR socket (state/direct.ts): an open
    loop duty and a bridge direction per motor. The hub takes both only while idle (P lets
    go of the speed controller first), so every set is read back."""

    changed = Signal()

    def __init__(self, comms: CommsHub, hub: HubStore) -> None:
        super().__init__()
        self._comms = comms
        self._hub = hub
        self.motors: dict[MotorId, DirectMotor] = {"A": DirectMotor(), "B": DirectMotor()}
        # set_duty_live()'s coalescing, per motor: the value still to send, and whether a send is running
        self._pending: dict[MotorId, int] = {}
        self._in_flight: set[MotorId] = set()
        self._was_idle: bool | None = None
        comms.state_changed.connect(self._apply)
        hub.changed.connect(self._on_hub)

    def _patch(self, motor: MotorId, **kw) -> None:
        self.motors[motor] = replace(self.motors[motor], **kw)
        self.changed.emit()

    async def load(self, motor: MotorId) -> None:
        """Read a fitted motor's duty and direction (MOTOR GP, GD); a failure lands in error."""
        try:
            r = await self._comms.motor_get(motor)
            self._patch(motor, duty=r.duty, requested=r.duty, direction=r.direction, error=None)
        except Exception as e:  # noqa: BLE001
            self._patch(motor, error=str(e))

    def set_duty_live(self, motor: MotorId, duty: int) -> None:
        """The Direct page's dial: set the duty as it turns. Never raises - a failure lands in
        duty_error. As CtrlStore.set_rpm_live(), one set per motor is in flight at a time,
        and only the latest value given meanwhile is sent next."""
        self._pending[motor] = duty
        self._patch(motor, requested=duty)
        if motor in self._in_flight:
            return
        self._in_flight.add(motor)
        spawn(self._send_duty(motor))

    async def _send_duty(self, motor: MotorId) -> None:
        try:
            while motor in self._pending:
                nxt = self._pending.pop(motor)
                try:
                    kept = await self._comms.motor_set_duty(motor, nxt)
                    # A set that finishes after a disconnect must not bring back a value _apply() has forgotten.
                    if self.motors[motor].duty is not None:
                        self._patch(motor, duty=kept, duty_error=None)
                except Exception as e:  # noqa: BLE001
                    if motor not in self._pending and self.motors[motor].duty is not None:
                        self._patch(motor, duty_error=RpmError(str(e)))
                        await self.load(motor)  # the hub kept something else - show what
        finally:
            self._in_flight.discard(motor)

    def stop(self, motor: MotorId) -> None:
        """The Stop button: 0% straight away. set_duty_live()'s pending value is a single
        slot, so 0 replaces whatever the dial left there, and at most the one set already
        in flight goes out before it."""
        self._patch(motor, duty_error=None, dial_reset=object())
        self.set_duty_live(motor, 0)

    async def set_direction(self, motor: MotorId, direction: MotorDirection) -> None:
        """Set the bridge direction (MOTOR D); a failure lands in error."""
        try:
            kept = await self._comms.motor_set_direction(motor, direction)
            self._patch(motor, direction=kept, error=None)
        except Exception as e:  # noqa: BLE001
            self._patch(motor, error=str(e))
            await self.load(motor)

    def _load_fitted(self) -> None:
        for m in MOTORS_FITTED:
            spawn(self.load(m))

    def _apply(self, s: CommsState) -> None:
        """Read the motors on each (re)connection to the hub; forget them when disconnected."""
        if s.status == "connected" and s.kind != "sim":
            self._load_fitted()
        elif s.status in ("connecting", "disconnected", "error"):
            self._pending.clear()
            self._was_idle = None
            self.motors = {"A": DirectMotor(), "B": DirectMotor()}
            self.changed.emit()

    def _on_hub(self) -> None:
        """A run or lift move ending leaves the bridge at 0% with no direction (the hub sets
        it idle), whatever was set here before - read it again."""
        hub = self._hub.hub
        idle = None if hub is None else hub.mode == "idle"
        if idle and self._was_idle is False:
            self._load_fitted()
        self._was_idle = idle


# --------------------------------------------------------------------------- lift
PingPhase = Literal["idle", "pinging", "done"]


class LiftStore(QObject):
    """The hub's LIFT0 socket (state/lift.ts)."""

    changed = Signal()

    def __init__(self, comms: CommsHub) -> None:
        super().__init__()
        self._comms = comms
        self.status: LiftStatus | None = None
        """Last status reported by the hub's LIFT0 socket"""
        self.done = False
        """Set when the hub reports the lift idle (move ended); cleared by the next start"""
        self.ping_phase: PingPhase = "idle"
        self.ping: PingReport | None = None
        """The last ping's outcome (ping_phase 'done')"""
        comms.lift_status.connect(self._on_status)
        # A new connection starts with no ping result.
        comms.state_changed.connect(lambda s: s.status == "connecting" and self._set(ping_phase="idle", ping=None))

    def _set(self, **kw) -> None:
        for k, v in kw.items():
            setattr(self, k, v)
        self.changed.emit()

    def _on_status(self, s: LiftStatus) -> None:
        self._set(status=s, done=not s.moving)

    async def start(self, distance: int, direction: LiftDirection) -> None:
        self._set(done=False)
        await self._comms.lift_start(distance, direction)

    async def down(self, max_edges: int) -> None:
        """Lower the lift to its ground sensor, max_edges at most"""
        self._set(done=False)
        await self._comms.lift_down(max_edges)

    async def stop(self) -> None:
        await self._comms.lift_stop()

    async def send_ping(self) -> None:
        """SerLink PING the hub's LIFT0 socket; ignored while one is in progress"""
        if self.ping_phase == "pinging":
            return
        self._set(ping_phase="pinging")
        try:
            report = await self._comms.lift_ping()
        except Exception as e:  # noqa: BLE001
            report = PingReport("error", 0, str(e))
        self._set(ping_phase="done", ping=report)


# --------------------------------------------------------------------------- app-kept settings
class ControlHubStore(QObject):
    """Config -> ControlHub settings that the app keeps (the hub keeps gain, max duty and
    target speed - see CtrlStore). Saved in settings.json."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.values: ControlHubSettings = settings.get().control_hub

    def save(self, lift_distance: int | None = None, dial_rpm_max: int | None = None) -> None:
        """Check each field given, keep the rest; raises ValueError if one is out of range."""
        nxt = replace(self.values)
        if lift_distance is not None:
            if not isinstance(lift_distance, int) or not 1 <= lift_distance <= LIFT_DISTANCE_MAX:
                raise ValueError(f"Lift distance must be a whole number from 1 to {LIFT_DISTANCE_MAX}")
            nxt.lift_distance = lift_distance
        if dial_rpm_max is not None:
            if not isinstance(dial_rpm_max, int) or not 1 <= dial_rpm_max <= CTRL_RPM_MAX:
                raise ValueError(f"Dial max speed must be a whole number from 1 to {CTRL_RPM_MAX}")
            nxt.dial_rpm_max = dial_rpm_max
        self.values = settings.update(control_hub=nxt).control_hub
        self.changed.emit()


DISPLAY_DEFAULTS = DisplaySettings()


class DisplayStore(QObject):
    """UI preferences (localStorage in the Electron app), persisted in settings.json."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.values: DisplaySettings = settings.get().display

    def set(self, **patch) -> None:
        self.values = settings.update(display=replace(self.values, **patch)).display
        self.changed.emit()

    def reset(self) -> None:
        """Everything back to the defaults (panels open again too, as in the Electron app)."""
        self.values = settings.update(display=DisplaySettings()).display
        self.changed.emit()
