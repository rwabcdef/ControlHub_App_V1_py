"""The interface shared by the serial, MQTT and simulator transports (transport.ts)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from ..types import HubState, LiftStatus, MqttLogLine, RawSample


@dataclass
class TransportEvents:
    """What a transport reports. All are called on the asyncio loop's thread."""

    sample: Callable[[RawSample], None]
    lift: Callable[[LiftStatus], None]
    """Lift status / done report"""
    hub: Callable[[HubState], None]
    """The hub's mode and direction, from a CTRL0 status frame (source once read with BGO)"""
    error: Callable[[Exception], None]
    """Non-fatal or fatal link problem; the transport may recover (see `reconnected`)"""
    reconnected: Callable[[], None]
    """Link restored after an error (e.g. MQTT auto-reconnect)"""
    close: Callable[[], None]
    """Link closed by the remote end / device unplugged"""
    mqtt_log: Callable[[MqttLogLine], None] | None = None
    """One line of MQTT traffic, either way (MQTT transport only)"""
    trace: Callable[[str], None] | None = None
    """SerLink trace line (frames sent / received, ack timeouts, ...); None = tracing off"""


class Transport(Protocol):
    """Common interface for serial, MQTT and the simulator.

    Beyond these, a transport defines only the hub calls its link carries - as the
    TS interface's optional methods - and CommsHub checks for them by name:
        socket_send(protocol: HubSocket, data, ack) -> str | None   serial, MQTT
        ctrl_get() -> CtrlReadback, ctrl_set(CtrlSettings) -> CtrlSettings,
        ctrl_start(), ctrl_stop(), ctrl_set_direction(CtrlDirection)  serial, MQTT
        motor_get(MotorId) -> MotorReadback, motor_set_duty(MotorId, duty) -> int,
        motor_set_direction(MotorId, MotorDirection) -> MotorDirection  serial, MQTT (MOTOR)
        lift_start(distance, LiftDirection), lift_down(max_edges),
        lift_stop(), lift_ping() -> PingReport                        MQTT (LIFT0)
        rtc_set(datetime) -> HubClockSetResult, rtc_get() -> HubClockReading  serial, MQTT (RTC00)
    """

    async def open(self) -> None: ...
    async def close(self) -> None: ...

    async def send(self, text: str) -> str | None:
        """Send one text command line to the device; returns any reply data (e.g. from a SerLink ack)"""
        ...
