"""MQTT transport: SerLink over MQTT, as the hub's SerLinkMqttAdapter (mqtt.ts).

Each payload is a serialised frame exactly as it would appear on the uart (the hub
publishes on telemetry_topic, subscribes to command_topic). A payload may hold
several newline-separated lines; non-SerLink lines are parsed as plain JSON / CSV
telemetry.

Every line in either direction - frames, acks, and anything else that arrives on
the telemetry topic - is passed to ev.mqtt_log, for the MQTT log page. The
LineWriter and the message handler are the only ways in and out, so nothing is
missed.

Threading: paho runs its own network thread (loop_start). Every callback is handed
to the asyncio loop with call_soon_threadsafe, so HubLink / SerLink only ever run
on the loop's (the UI's) thread.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import time
import uuid
from urllib.parse import urlsplit

import paho.mqtt.client as mqtt

from ..types import (CtrlDirection, CtrlReadback, CtrlSettings, HubClockReading, HubClockSetResult, HubSocket,
                     LiftDirection, MotorDirection, MotorId, MotorReadback, MqttConfig, MqttLogLine, PingReport)
from .errors import CommsError
from .hub_link import HubLink
from .transport import TransportEvents

CONNECT_TIMEOUT_S = 5.0
RECONNECT_S = 2


def _client_for(url: str) -> tuple[mqtt.Client, str, int]:
    """mqtt://host:1883, mqtts://host:8883, ws://host:9001[/path] or wss://..."""
    u = urlsplit(url)
    scheme = u.scheme.lower()
    if scheme not in ("mqtt", "tcp", "mqtts", "ssl", "ws", "wss") or not u.hostname:
        raise CommsError(f"Unsupported broker URL {url!r} - use mqtt://, mqtts://, ws:// or wss://")
    ws = scheme in ("ws", "wss")
    tls = scheme in ("mqtts", "ssl", "wss")
    port = u.port or {"mqtt": 1883, "tcp": 1883, "mqtts": 8883, "ssl": 8883, "ws": 80, "wss": 443}[scheme]
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"controlhub-{uuid.uuid4().hex[:8]}",
                         transport="websockets" if ws else "tcp")
    if ws:
        client.ws_set_options(path=u.path or "/mqtt")
    if tls:
        client.tls_set()
    return client, u.hostname, port


class MqttTransport:
    def __init__(self, cfg: MqttConfig, ev: TransportEvents) -> None:
        self._cfg = cfg
        self._ev = ev
        self._client: mqtt.Client | None = None
        self._link: HubLink | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._opened = False
        self._closing = False

    # ---- open / close
    async def open(self) -> None:
        cfg = self._cfg
        # Brokers deliver to the publisher too, so we'd receive (and ack) our own frames.
        if cfg.telemetry_topic == cfg.command_topic:
            raise CommsError("Telemetry and command topics must differ")
        loop = self._loop = asyncio.get_running_loop()
        client, host, port = _client_for(cfg.url)
        self._client = client
        if cfg.username:
            client.username_pw_set(cfg.username, cfg.password or None)
        client.reconnect_delay_set(min_delay=RECONNECT_S, max_delay=RECONNECT_S)
        self._link = HubLink(self._write_line, self._ev, lift=True)

        ready: asyncio.Future = loop.create_future()

        def hop(fn, *args):
            if not loop.is_closed():
                loop.call_soon_threadsafe(fn, *args)

        def on_connect(_c, _u, _flags, reason_code, _props):
            hop(self._on_connect, reason_code, ready)

        def on_subscribe(_c, _u, _mid, reason_codes, _props):
            hop(self._on_subscribe, reason_codes, ready)

        client.on_connect = on_connect
        client.on_subscribe = on_subscribe
        client.on_disconnect = lambda *_a: hop(self._on_disconnect)
        client.on_message = lambda _c, _u, msg: hop(self._on_message, msg.topic, msg.payload)

        try:
            client.connect_async(host, port, keepalive=60)
            client.loop_start()
            # paho silently retries refused connections, so enforce our own timeout.
            await asyncio.wait_for(ready, CONNECT_TIMEOUT_S + 1)
        except (asyncio.TimeoutError, TimeoutError):
            await self._shutdown()
            raise CommsError(f"Could not connect to {cfg.url}") from None
        except BaseException:
            await self._shutdown()
            raise
        self._opened = True

    async def close(self) -> None:
        self._closing = True
        if self._link is not None:
            self._link.close()
            self._link = None
        await self._shutdown()

    async def _shutdown(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        client.on_disconnect = None
        client.on_message = None
        client.disconnect()
        await asyncio.to_thread(client.loop_stop)  # joins paho's thread

    # ---- paho events, on the loop
    def _on_connect(self, reason_code, ready: asyncio.Future) -> None:
        if self._client is None:
            return
        if reason_code.is_failure:
            if not ready.done():
                ready.set_exception(CommsError(f"MQTT connection refused: {reason_code}"))
            return
        # Subscribed on every connect: paho, unlike mqtt.js, does not resubscribe itself.
        self._client.subscribe(self._cfg.telemetry_topic)
        if self._opened and not self._closing:
            self._ev.reconnected()

    def _on_subscribe(self, reason_codes, ready: asyncio.Future) -> None:
        if ready.done():
            return
        bad = [rc for rc in reason_codes if rc.is_failure]
        if bad:
            ready.set_exception(CommsError(f"Could not subscribe to {self._cfg.telemetry_topic}: {bad[0]}"))
        else:
            ready.set_result(None)

    def _on_disconnect(self) -> None:
        # Only reported once the first connection has succeeded (as mqtt.ts).
        if self._opened and not self._closing:
            self._ev.error(CommsError("MQTT broker offline, reconnecting…"))

    def _on_message(self, topic: str, payload: bytes) -> None:
        link = self._link
        if link is None or topic != self._cfg.telemetry_topic:
            return
        for line in payload.decode("utf-8", errors="replace").split("\n"):
            if line.strip() and self._ev.mqtt_log is not None:
                self._ev.mqtt_log(MqttLogLine(time.time() * 1000, "in", topic, line.rstrip("\r")))
            link.receive_line(line)

    # ---- out
    async def _write_line(self, line: str) -> None:
        client = self._client
        if client is None or not client.is_connected():
            raise CommsError("MQTT not connected")
        info = client.publish(self._cfg.command_topic, line + "\n")
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise CommsError(f"MQTT publish failed: {mqtt.error_string(info.rc)}")
        if self._ev.mqtt_log is not None:
            self._ev.mqtt_log(MqttLogLine(time.time() * 1000, "out", self._cfg.command_topic, line))

    def _live(self) -> HubLink:
        if self._link is None or self._client is None or not self._client.is_connected():
            raise CommsError("MQTT not connected")
        return self._link

    async def send(self, text: str) -> str | None:
        return await self._live().send(text)

    async def socket_send(self, protocol: HubSocket, data: str, ack: bool) -> str | None:
        return await self._live().socket_send(protocol, data, ack)

    async def ctrl_get(self) -> CtrlReadback:
        return await self._live().ctrl_get()

    async def ctrl_set(self, s: CtrlSettings) -> CtrlSettings:
        return await self._live().ctrl_set(s)

    async def ctrl_start(self) -> None:
        await self._live().ctrl_start()

    async def ctrl_stop(self) -> None:
        await self._live().ctrl_stop()

    async def ctrl_set_direction(self, direction: CtrlDirection) -> None:
        await self._live().ctrl_set_direction(direction)

    async def motor_get(self, motor: MotorId) -> MotorReadback:
        return await self._live().motor_get(motor)

    async def motor_set_duty(self, motor: MotorId, duty: int) -> int:
        return await self._live().motor_set_duty(motor, duty)

    async def motor_set_direction(self, motor: MotorId, direction: MotorDirection) -> MotorDirection:
        return await self._live().motor_set_direction(motor, direction)

    async def rtc_set(self, when: datetime) -> HubClockSetResult:
        return await self._live().rtc_set(when)

    async def rtc_get(self) -> HubClockReading:
        return await self._live().rtc_get()

    async def lift_start(self, distance: int, direction: LiftDirection) -> None:
        await self._live().lift_start(distance, direction)

    async def lift_down(self, max_edges: int) -> None:
        await self._live().lift_down(max_edges)

    async def lift_stop(self) -> None:
        await self._live().lift_stop()

    async def lift_ping(self) -> PingReport:
        return await self._live().lift_ping()
