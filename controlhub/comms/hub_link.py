"""The ControlHubAA26 hub's SerLink sockets over one line-oriented link (hubLink.ts).

Shared by the serial and MQTT transports - the hub runs the same CTRL0 and MOTOR
sockets on uart2 (SerLink0) and on MQTT (SerLink2). LIFT0 exists only on the MQTT link.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime

from ..types import (CTRL_DUTY_MAX, CTRL_DUTY_MIN, CTRL_GAIN_MAX, CTRL_GAIN_SCALE, CTRL_RPM_MAX, LIFT_DISTANCE_MAX,
                     MOTOR_DUTY_MAX, MOTORS_FITTED, CtrlDirection, CtrlReadback, CtrlSettings, HubClockSetResult, HubSocket, HubState,
                     LiftDirection, MotorDirection, MotorId, MotorReadback, PingReport)
from .errors import CommsError
from .parser import parse_ctrl_status, parse_hub_mode, parse_lift_status, parse_line
from .serlink.frame import Frame
from .serlink.serlink import LineWriter, SendFrameResult, SerLink, Socket
from .transport import TransportEvents

CTRL_PROTOCOL = "CTRL0"
"""The hub's speed controller socket: status frames in, controller commands out."""
MOTOR_PROTOCOL = "MOTOR"
"""The hub's direct motor socket: open loop duty and bridge direction, for the Direct
page. On both the hub's links (uart2 and MQTT)."""
LIFT_PROTOCOL = "LIFT0"
"""The hub's lift socket - only on its MQTT link (SerLink2)"""
_LIFT_ID = "B"
"""The only lift on the hub"""
RTC_PROTOCOL = "RTC00"
"""The hub's real time clock socket - on both its links (uart2 and MQTT)"""

_BGA_RE = re.compile(r"^(\d{6})\.(\d{4})\.(\d{4})$")
_MOTOR_DIRECTION_FROM_CHAR: dict[str, MotorDirection] = {"F": "forward", "R": "reverse", "D": "disabled"}
_MOTOR_DIRECTION_TO_CHAR = {v: k for k, v in _MOTOR_DIRECTION_FROM_CHAR.items()}


def _is_whole(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _fmt_gain(g: float) -> str:
    """A gain as JS would print it (0.002, not 0.002000 or 2e-03)."""
    return format(g, ".6f").rstrip("0").rstrip(".") or "0"


class HubLink:
    def __init__(self, write: LineWriter, ev: TransportEvents, lift: bool = False) -> None:
        """Construct on the asyncio loop (SerLink captures it). lift: acquire the LIFT0 socket."""
        self._ev = ev
        self._hub: HubState | None = None
        """The hub's state as last reported, to spot a change of mode"""
        self._tasks: set[asyncio.Task] = set()
        self.serlink = SerLink(write, ev.trace)
        self.ctrl: Socket = self.serlink.acquire_socket(CTRL_PROTOCOL, self._on_ctrl)
        self.motor: Socket = self.serlink.acquire_socket(MOTOR_PROTOCOL)
        """Sends only - the hub never sends MOTOR frames unasked"""
        self.lift: Socket | None = self.serlink.acquire_socket(LIFT_PROTOCOL, self._on_lift) if lift else None
        self.rtc: Socket = self.serlink.acquire_socket(RTC_PROTOCOL)
        """Sends only - the hub never sends RTC00 frames unasked"""

    # ---- in
    def receive_line(self, line: str) -> None:
        """Handle one received line: a SerLink frame, or else plain JSON / CSV telemetry."""
        if self.serlink.receive_line(line):
            return
        s = parse_line(line)
        if s is not None:
            self._ev.sample(s)

    def _on_ctrl(self, frame: Frame) -> None:
        parsed = parse_ctrl_status(frame.data)
        if parsed is None:
            return
        sample, hub = parsed
        self._ev.sample(sample)
        self._on_hub_status(hub)

    def _on_lift(self, frame: Frame) -> None:
        s = parse_lift_status(frame.data)
        if s is not None:
            self._ev.lift(s)

    def _on_hub_status(self, s: HubState) -> None:
        """A CTRL0 status frame's mode and direction. Passed on at once; when the mode
        changes to a run, who started it is read with BGO and passed on again. Idle has
        no source."""
        changed = self._hub is None or self._hub.mode != s.mode
        source = "none" if s.mode == "idle" else None if changed else self._hub.source  # type: ignore[union-attr]
        self._hub = HubState(s.mode, s.direction, source, s.run_rpm)
        self._ev.hub(self._hub)
        if changed and s.mode != "idle":
            task = asyncio.get_running_loop().create_task(self._read_source())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _read_source(self) -> None:
        try:
            data = await self._send_ctrl("BGO")
        except CommsError:
            return  # The next mode change tries again; the status frames carry on regardless.
        m = parse_hub_mode(data or "")
        if m is not None and self._hub is not None and m[0] == self._hub.mode:
            h = self._hub
            self._hub = HubState(h.mode, h.direction, m[1], h.run_rpm)
            self._ev.hub(self._hub)

    # ---- out
    async def send(self, text: str) -> str | None:
        """Send a command. A complete SerLink frame (e.g. CTRL0T516006BR0120, as listed in
        the firmware's main_tasks.cpp) is sent as is; anything else is sent as CTRL0 data
        (e.g. BR0120) in a 'T' frame. Raises unless acked OK. Returns any data piggybacked
        on the ack (e.g. BGR -> 0120)."""
        cmd = text.strip()
        if not cmd:
            raise CommsError("Empty command")
        frame = Frame.from_string(cmd)
        if frame is not None:
            return _check_result(frame.protocol, await self.serlink.send_frame(frame))
        return _check_result(CTRL_PROTOCOL, await self.ctrl.send_data(cmd, True))

    async def ctrl_get(self) -> CtrlReadback:
        """Read controller B's settings and the hub's state:
            BGA -> 002000.0150.0148  gain, target RPM, measured RPM
            BGM -> 050               max duty
            BGD -> F                 selected direction
            BGO -> CP                mode and who started the run"""
        data = await self._send_ctrl("BGA")
        m = _BGA_RE.match(data or "")
        if not m:
            raise CommsError(f'{CTRL_PROTOCOL}: unexpected BGA reply "{data or ""}"')
        max_duty = await self._send_ctrl("BGM")
        if not re.fullmatch(r"\d{3}", max_duty or ""):
            raise CommsError(f'{CTRL_PROTOCOL}: unexpected BGM reply "{max_duty or ""}"')
        d = await self._send_ctrl("BGD")
        if d not in ("F", "R"):
            raise CommsError(f'{CTRL_PROTOCOL}: unexpected BGD reply "{d or ""}"')
        mode = await self._send_ctrl("BGO")
        hm = parse_hub_mode(mode or "")
        if hm is None:
            raise CommsError(f'{CTRL_PROTOCOL}: unexpected BGO reply "{mode or ""}"')

        # Only the status frame carries the run's target - keep it through the same run.
        keep = self._hub.run_rpm if self._hub is not None and self._hub.mode == hm[0] else None
        hub = HubState(hm[0], "reverse" if d == "R" else "forward", hm[1], keep)
        self._hub = hub
        self._ev.hub(hub)
        return CtrlReadback(gain_i=int(m[1]) / CTRL_GAIN_SCALE, rpm=int(m[2]), measured_rpm=int(m[3]),
                            max_duty=int(max_duty), hub=hub)

    async def ctrl_set(self, s: CtrlSettings) -> CtrlSettings:
        """Set controller B's integral gain, target RPM and / or max duty (BI002000, BR0120,
        BM050). Each is read back (BGI, BGR, BGM) - the hub refuses BR during a lift move,
        and a max duty out of its range - and the result is what the hub now holds; raises
        if a read-back value differs from the one sent. None of them starts anything."""
        out = CtrlSettings()
        if s.gain_i is not None:
            micro = _gain_to_micro(s.gain_i)
            await self._send_ctrl(f"BI{micro:06d}")
            back = await self._send_ctrl("BGI")
            if not re.fullmatch(r"\d{6}", back or ""):
                raise CommsError(f'{CTRL_PROTOCOL}: unexpected BGI reply "{back or ""}"')
            if int(back) != micro:  # type: ignore[arg-type]
                raise CommsError(f"Gain read back as {_fmt_gain(int(back) / CTRL_GAIN_SCALE)}, "  # type: ignore[arg-type]
                                 f"not {_fmt_gain(micro / CTRL_GAIN_SCALE)}")
            out.gain_i = micro / CTRL_GAIN_SCALE
        if s.rpm is not None:
            if not _is_whole(s.rpm) or not 0 <= s.rpm <= CTRL_RPM_MAX:
                raise CommsError(f"RPM must be a whole number from 0 to {CTRL_RPM_MAX}")
            await self._send_ctrl(f"BR{s.rpm:04d}")
            # The hub refuses a new target during a lift move, so the read back is the check.
            back = await self._send_ctrl("BGR")
            if not re.fullmatch(r"\d{4}", back or ""):
                raise CommsError(f'{CTRL_PROTOCOL}: unexpected BGR reply "{back or ""}"')
            if int(back) != s.rpm:  # type: ignore[arg-type]
                raise CommsError(f"The hub kept {int(back)} RPM, not {s.rpm} (refused during a lift move)")  # type: ignore[arg-type]
            out.rpm = s.rpm
        if s.max_duty is not None:
            if not _is_whole(s.max_duty) or not CTRL_DUTY_MIN <= s.max_duty <= CTRL_DUTY_MAX:
                raise CommsError(f"Max duty must be a whole number from {CTRL_DUTY_MIN} to {CTRL_DUTY_MAX}")
            await self._send_ctrl(f"BM{s.max_duty:03d}")
            # The hub ignores a value it won't take, so the read back is the check.
            back = await self._send_ctrl("BGM")
            if not re.fullmatch(r"\d+", back or "") or int(back) != s.max_duty:  # type: ignore[arg-type]
                raise CommsError(f"Max duty read back as {back if back is not None else '?'}, not {s.max_duty}")
            out.max_duty = s.max_duty
        return out

    async def ctrl_start(self) -> None:
        """Start a Control run at the target speed in the selected direction: CTRL0T...BS.
        The hub ignores it unless idle - the status frames that follow (or BGO) say whether
        it started."""
        await self._send_ctrl("BS")

    async def ctrl_stop(self) -> None:
        """Stop whatever is running - a Control run or a lift move: CTRL0T...BX."""
        await self._send_ctrl("BX")

    async def ctrl_set_direction(self, direction: CtrlDirection) -> None:
        """Select the direction of the next Control run: CTRL0T...BDF / BDR. Ignored unless idle."""
        if direction not in ("forward", "reverse"):
            raise CommsError(f'Direction must be forward or reverse, not "{direction}"')
        await self._send_ctrl("BDF" if direction == "forward" else "BDR")

    async def motor_get(self, motor: MotorId) -> MotorReadback:
        """Read a motor's duty and bridge direction:
            BGP -> 030   duty %, 3 digits
            BGD -> F     direction, F / R / D (disabled: both IN pins low)"""
        _check_motor(motor)
        duty = await self._send_motor(f"{motor}GP")
        if not re.fullmatch(r"\d{3}", duty or ""):
            raise CommsError(f'{MOTOR_PROTOCOL}: unexpected {motor}GP reply "{duty or ""}"')
        d = await self._send_motor(f"{motor}GD")
        direction = _MOTOR_DIRECTION_FROM_CHAR.get(d or "")
        if direction is None:
            raise CommsError(f'{MOTOR_PROTOCOL}: unexpected {motor}GD reply "{d or ""}"')
        return MotorReadback(int(duty), direction)  # type: ignore[arg-type]

    async def motor_set_duty(self, motor: MotorId, duty: int) -> int:
        """Set a motor's duty, open loop: MOTOR BP030. The hub refuses it unless idle (it
        lets go of the speed controller first), silently - so it is read back (BGP), and
        raises if the hub kept another value. Returns the duty the hub now holds."""
        _check_motor(motor)
        if not _is_whole(duty) or not 0 <= duty <= MOTOR_DUTY_MAX:
            raise CommsError(f"Duty must be a whole number from 0 to {MOTOR_DUTY_MAX}")
        await self._send_motor(f"{motor}P{duty:03d}")
        back = await self._send_motor(f"{motor}GP")
        if not re.fullmatch(r"\d{3}", back or ""):
            raise CommsError(f'{MOTOR_PROTOCOL}: unexpected {motor}GP reply "{back or ""}"')
        if int(back) != duty:  # type: ignore[arg-type]
            raise CommsError(f"The hub kept {int(back)}%, not {duty}% (refused unless idle)")  # type: ignore[arg-type]
        return duty

    async def motor_set_direction(self, motor: MotorId, direction: MotorDirection) -> MotorDirection:
        """Set a motor's bridge direction: MOTOR BDF / BDR / BDD. Refused unless idle, like
        the duty, so read back (BGD) the same way."""
        _check_motor(motor)
        c = _MOTOR_DIRECTION_TO_CHAR.get(direction)
        if c is None:
            raise CommsError(f'Direction must be forward, reverse or disabled, not "{direction}"')
        await self._send_motor(f"{motor}D{c}")
        back = await self._send_motor(f"{motor}GD")
        kept = _MOTOR_DIRECTION_FROM_CHAR.get(back or "")
        if kept is None:
            raise CommsError(f'{MOTOR_PROTOCOL}: unexpected {motor}GD reply "{back or ""}"')
        if kept != direction:
            raise CommsError(f"The hub kept {kept}, not {direction} (refused unless idle)")
        return direction

    async def lift_start(self, distance: int, direction: LiftDirection) -> None:
        """Start the lift for `distance` edges in `direction`, e.g. LIFT0U645006BSF234
        (forward) or LIFT0U645006BSR234 (reverse). Sent as 'U', so this only confirms the
        frame was published; the hub reports the move's end with an idle status frame. The
        speed is the controller's (CTRL0 BR), not part of the start."""
        lift = self._need_lift()
        if not _is_whole(distance) or not 1 <= distance <= LIFT_DISTANCE_MAX:
            raise CommsError(f"Lift distance must be a whole number from 1 to {LIFT_DISTANCE_MAX}")
        if direction not in ("forward", "reverse"):
            raise CommsError(f'Lift direction must be forward or reverse, not "{direction}"')
        d = "F" if direction == "forward" else "R"
        _check_result(LIFT_PROTOCOL, await lift.send_data(f"{_LIFT_ID}S{d}{distance}", False))

    async def lift_down(self, max_edges: int) -> None:
        """Lower the lift until its ground sensor (PB9) trips, giving up after `max_edges`:
        LIFT0U645006BG2000. Sent as 'U'; like a start, the hub reports the move's end with
        an idle status frame."""
        lift = self._need_lift()
        if not _is_whole(max_edges) or not 1 <= max_edges <= LIFT_DISTANCE_MAX:
            raise CommsError(f"Lift max edges must be a whole number from 1 to {LIFT_DISTANCE_MAX}")
        _check_result(LIFT_PROTOCOL, await lift.send_data(f"{_LIFT_ID}G{max_edges}", False))

    async def lift_stop(self) -> None:
        """Stop the lift: LIFT0U645002BX, sent as 'U'."""
        _check_result(LIFT_PROTOCOL, await self._need_lift().send_data(f"{_LIFT_ID}X", False))

    async def socket_send(self, protocol: HubSocket, data: str, ack: bool) -> str | None:
        """Send raw data to a socket (e.g. CTRL0 BGA, LIFT0 BSF234) as a 'T' frame (ack=True:
        raises unless acked OK, returns any data on the ack) or a 'U' frame."""
        if protocol == CTRL_PROTOCOL:
            socket: Socket | None = self.ctrl
        elif protocol == LIFT_PROTOCOL:
            socket = self.lift
            if socket is None:
                raise CommsError(f"{protocol} is only available over MQTT")
        else:
            raise CommsError(f"Unknown socket {protocol}")
        payload = data.strip()
        if not payload:
            raise CommsError("Empty payload")
        return _check_result(protocol, await socket.send_data(payload, ack))

    async def rtc_set(self, when: datetime) -> HubClockSetResult:
        """Set the hub's clock to `when`, as this PC's local time, 24 hour:
        RTC00T570015S20261023143005. Done on the ack, so the answer says whether it was
        taken: S1 -> 'ok', S0 -> 'refused' (outside 2000..2099). A plain ACK_OK ->
        'noSocket' (firmware without a clock). Raises CommsError with no ack."""
        data = _check_result(RTC_PROTOCOL, await self.rtc.send_data(f"S{when:%Y%m%d%H%M%S}", True))
        if data is None:
            return "noSocket"
        if data == "S1":
            return "ok"
        if data == "S0":
            return "refused"
        raise CommsError(f'{RTC_PROTOCOL}: unexpected S reply "{data}"')

    async def lift_ping(self) -> PingReport:
        """SerLink PING the hub's LIFT0 socket (LIFT0S...PING). Never raises once sent."""
        o = await self._need_lift().ping()
        return PingReport(o.result, o.elapsed_ms, str(o.error) if o.error is not None else None)

    def close(self) -> None:
        self.serlink.close()
        for t in self._tasks:
            t.cancel()

    def _need_lift(self) -> Socket:
        if self.lift is None:
            raise CommsError(f"{LIFT_PROTOCOL} is only available over MQTT")
        return self.lift

    async def _send_motor(self, data: str) -> str | None:
        """Send MOTOR data in a 'T' frame; returns any data on the ack."""
        return _check_result(MOTOR_PROTOCOL, await self.motor.send_data(data, True))

    async def _send_ctrl(self, data: str) -> str | None:
        """Send CTRL0 data in a 'T' frame; returns any data on the ack."""
        return _check_result(CTRL_PROTOCOL, await self.ctrl.send_data(data, True))


def _check_motor(motor: MotorId) -> None:
    """Only a fitted channel - the hub sends A to motorB until motorA exists."""
    if motor not in MOTORS_FITTED:
        raise CommsError(f"Motor {motor} is not fitted")


def _gain_to_micro(gain: float) -> int:
    """Gain as the hub's integer millionths; raises unless 0..CTRL_GAIN_MAX with at most 6 decimals."""
    try:
        g = float(gain)
        micro = round(g * CTRL_GAIN_SCALE)
        ok = 0 <= micro <= CTRL_GAIN_MAX * CTRL_GAIN_SCALE and abs(g * CTRL_GAIN_SCALE - micro) <= 1e-6
    except (TypeError, ValueError, OverflowError):
        ok = False
    if not ok:
        raise CommsError(f"Gain must be 0 to {CTRL_GAIN_MAX}, with at most 6 decimal places")
    return micro


def _check_result(protocol: str, r: SendFrameResult) -> str | None:
    if r.status == "ok":
        return r.ack_data
    if r.status == "nack":
        raise CommsError(f"{protocol}: command rejected (ack code {r.ack.data_len if r.ack else '?'})")
    if r.status == "timeout":
        raise CommsError(f"{protocol}: no ack from the hub")
    if r.status == "closed":
        raise CommsError("Link closed")
    raise CommsError(str(r.error) if r.error is not None else f"{protocol}: send failed")
