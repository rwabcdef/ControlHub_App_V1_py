"""Owns the active transport and reports what it hears (comms/hub.ts + the IPC handlers).

The Electron app split this across processes; here it is one QObject. Samples go
straight into the telemetry store (no 16 ms IPC batching); the hub's state, lift
status and MQTT log lines are Qt signals, at their own low rates.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Signal

from ..asyncutil import spawn
from ..settings import settings
from ..state.telemetry import TelemetryStore
from ..types import (CommsConfig, CommsState, CtrlDirection, CtrlReadback, CtrlSettings, HubSocket, LiftDirection,
                     MotorDirection, MotorId, MotorReadback, PingReport, RawSample)
from .errors import CommsError
from .mqtt_transport import MqttTransport
from .serial_transport import SerialTransport, list_serial_ports
from .simulator import SimTransport
from .status_thinner import StatusThinner
from .transport import Transport, TransportEvents

log = logging.getLogger("SerLink")

SERLINK_TRACE = bool(os.environ.get("SERLINK_DEBUG"))
"""Trace SerLink traffic to the console (python -m controlhub --debug sets it)."""

HUB_CLOCK_RETRY_S = 10.0
"""Until the hub's clock has been set this app run, try again this often while connected
(see _hub_clock_loop)"""

clock_log = logging.getLogger("controlhub.hub_clock")


class CommsHub(QObject):
    state_changed = Signal(object)
    """CommsState"""
    hub_state = Signal(object)
    """HubState, from each CTRL0 status frame (source once read with BGO)"""
    lift_status = Signal(object)
    """LiftStatus, from the hub's LIFT0 socket"""
    mqtt_log = Signal(object)
    """MqttLogLine, already thinned (1 status frame in 10 while running)"""

    def __init__(self, telemetry: TelemetryStore) -> None:
        super().__init__()
        self._telemetry = telemetry
        self._transport: Transport | None = None
        self._t0 = 0.0
        self._state = CommsState("disconnected", settings.get().comms.kind)
        self._hub_clock_done = False
        """The hub's clock has been dealt with this app run - set, or found not settable"""
        self._hub_clock_busy = False

    @property
    def state(self) -> CommsState:
        return self._state

    def list_ports(self):
        return list_serial_ports()

    async def connect(self, cfg: CommsConfig | None = None) -> None:
        cfg = cfg or settings.get().comms
        await self.disconnect()
        self._set_state(CommsState("connecting", cfg.kind))
        self._t0 = time.perf_counter()

        transport: Transport | None = None

        def live() -> bool:
            """Ignore late events from a transport that has since been replaced."""
            return self._transport is transport

        # The logs keep 1 status frame in 10 while running (telemetry gets them all).
        log_thinner, trace_thinner = StatusThinner(), StatusThinner()

        def sample(s: RawSample) -> None:
            if live():
                t = s.t if s.t is not None else (time.perf_counter() - self._t0) * 1000
                self._telemetry.push(t, s.rpm, s.duty, s.current)

        def mqtt_line(line) -> None:
            if live() and log_thinner.keep(line.line):
                self.mqtt_log.emit(line)

        def trace(msg: str) -> None:
            if live() and trace_thinner.keep(msg):
                stamp = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
                log.info("%s %s %s", stamp, cfg.kind, msg)

        def error(err: Exception) -> None:
            if live():
                self._set_state(CommsState("error", cfg.kind, str(err)))

        def reconnected() -> None:
            if live():
                self._set_state(CommsState("connected", cfg.kind))
                if transport is not None:
                    spawn(self._set_hub_clock(transport))

        def closed() -> None:
            if live():
                spawn(self.disconnect())

        ev = TransportEvents(
            sample=sample,
            lift=lambda s: live() and self.lift_status.emit(s),
            hub=lambda s: live() and self.hub_state.emit(s),
            error=error, reconnected=reconnected, close=closed, mqtt_log=mqtt_line,
            trace=trace if SERLINK_TRACE else None)

        if cfg.kind == "serial":
            transport = SerialTransport(cfg.serial, ev)
        elif cfg.kind == "mqtt":
            transport = MqttTransport(cfg.mqtt, ev)
        else:
            transport = SimTransport(ev)
        self._transport = transport
        try:
            await transport.open()
        except Exception as err:  # noqa: BLE001 - shown to the user as the connection error
            self._transport = None
            try:
                await transport.close()
            except Exception:  # noqa: BLE001
                pass
            self._set_state(CommsState("error", cfg.kind, str(err) or type(err).__name__))
            return
        if self._transport is transport:
            self._set_state(CommsState("connected", cfg.kind))
            spawn(self._hub_clock_loop(transport))

    async def disconnect(self) -> None:
        t, self._transport = self._transport, None
        if t is not None:
            try:
                await t.close()
            except Exception:  # noqa: BLE001
                pass
            self._set_state(CommsState("disconnected", self._state.kind))

    # ---- commands (the IPC handlers' checks and messages)
    def _need(self, name: str, message: str):
        if self._transport is None:
            raise CommsError("Not connected")
        fn = getattr(self._transport, name, None)
        if fn is None:
            raise CommsError(message)
        return fn

    async def send(self, text: str) -> str | None:
        return await self._need("send", "Not connected")(text)

    async def socket_send(self, protocol: HubSocket, data: str, ack: bool) -> str | None:
        return await self._need("socket_send", "Socket commands need a serial or MQTT connection")(protocol, data, ack)

    async def ctrl_get(self) -> CtrlReadback:
        return await self._need("ctrl_get", "Controller settings need a serial or MQTT connection")()

    async def ctrl_set(self, s: CtrlSettings) -> CtrlSettings:
        return await self._need("ctrl_set", "Controller settings need a serial or MQTT connection")(s)

    async def ctrl_start(self) -> None:
        await self._need("ctrl_start", "Control runs need a serial or MQTT connection")()

    async def ctrl_stop(self) -> None:
        await self._need("ctrl_stop", "Control runs need a serial or MQTT connection")()

    async def ctrl_set_direction(self, direction: CtrlDirection) -> None:
        await self._need("ctrl_set_direction", "Control runs need a serial or MQTT connection")(direction)

    async def motor_get(self, motor: MotorId) -> MotorReadback:
        return await self._need("motor_get", "Direct motor control needs a serial or MQTT connection")(motor)

    async def motor_set_duty(self, motor: MotorId, duty: int) -> int:
        return await self._need("motor_set_duty", "Direct motor control needs a serial or MQTT connection")(motor, duty)

    async def motor_set_direction(self, motor: MotorId, direction: MotorDirection) -> MotorDirection:
        return await self._need("motor_set_direction",
                                "Direct motor control needs a serial or MQTT connection")(motor, direction)

    async def lift_start(self, distance: int, direction: LiftDirection) -> None:
        await self._need("lift_start", "Lift control needs an MQTT connection")(distance, direction)

    async def lift_down(self, max_edges: int) -> None:
        await self._need("lift_down", "Lift control needs an MQTT connection")(max_edges)

    async def lift_stop(self) -> None:
        await self._need("lift_stop", "Lift control needs an MQTT connection")()

    async def lift_ping(self) -> PingReport:
        return await self._need("lift_ping", "Lift ping needs an MQTT connection")()

    # ---- the hub's clock
    async def _hub_clock_loop(self, transport: Transport) -> None:
        """Config -> ControlHub "Set hub date time on app launch" (on by default): set the
        hub's clock (RTC00 S) to this PC's local time, once per app run. Tried as soon as a
        connection opens and then every HUB_CLOCK_RETRY_S while it stays open, because the
        hub may not be up yet - over MQTT the broker connects whether or not the hub is
        there - until the hub answers. S0 (refused) or no RTC00 socket ends it too: a
        retry would get the same answer. Not on the simulator, which has no rtc_set."""
        if getattr(transport, "rtc_set", None) is None:
            return
        while not self._hub_clock_done and self._transport is transport:
            await self._set_hub_clock(transport)
            if self._hub_clock_done:
                return
            await asyncio.sleep(HUB_CLOCK_RETRY_S)

    async def _set_hub_clock(self, transport: Transport) -> None:
        rtc_set = getattr(transport, "rtc_set", None)
        if self._hub_clock_done or self._hub_clock_busy or self._transport is not transport or rtc_set is None:
            return
        # Read each time: "on launch" means the setting as it is at the first chance, so
        # switching it on later in the run does nothing until the next.
        if not settings.get().control_hub.set_hub_time_on_launch:
            self._hub_clock_done = True
            return
        self._hub_clock_busy = True
        try:
            now = datetime.now()
            result = await rtc_set(now)
            if result == "ok":
                clock_log.info("set to %s", now.strftime("%Y-%m-%d %H:%M:%S"))
            elif result == "refused":
                clock_log.warning("the hub refused %s", now.strftime("%Y-%m-%d %H:%M:%S"))
            else:
                clock_log.warning("the hub has no RTC00 socket (firmware without a clock)")
            self._hub_clock_done = True
        except CommsError:
            pass  # no ack (hub not up yet) or the link went: the next try, or connection, goes again
        finally:
            self._hub_clock_busy = False

    def _set_state(self, s: CommsState) -> None:
        self._state = s
        self.state_changed.emit(s)
