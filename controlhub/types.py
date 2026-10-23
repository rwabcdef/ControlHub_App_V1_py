"""Types and constants shared by the comms layer, the stores and the UI.

A port of the Electron app's src/shared/types.ts. Field limits mirror the
firmware's digit widths and ranges - see the hub repo's sockets_summary.txt,
the protocol contract between the hub, this app and the Arduino remote hub.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

# --------------------------------------------------------------------------- telemetry

MotorField = Literal["rpm", "duty", "current"]
MOTOR_FIELDS: tuple[MotorField, ...] = ("rpm", "duty", "current")


@dataclass
class RawSample:
    """A sample as decoded from the wire. `t` is ms; None means "use host time"."""

    rpm: float
    """Shaft speed, RPM"""
    duty: float
    """PWM duty cycle, 0-100 %"""
    current: float
    """Motor current, A (NaN if the source doesn't report it)"""
    t: float | None = None


# --------------------------------------------------------------------------- lift

@dataclass
class LiftStatus:
    """A lift's state, from the hub's LIFT0 socket, e.g. BI000234.000234"""

    lift: str
    """Lift id, e.g. 'B'"""
    moving: bool
    travelled: int
    """Edges travelled since the last start"""
    target: int
    """That start's target, edges"""


LIFT_DISTANCE_MAX = 999_999
"""Lift start distance range, edges (the hub takes 1..6 digits)"""

LiftDirection = Literal["forward", "reverse"]
"""Which way a lift start moves - the F / R in LIFT0 BSF234 / BSR234"""

# --------------------------------------------------------------------------- controller

CTRL_GAIN_SCALE = 1_000_000
"""The hub takes the gain as 6 digits of millionths, RPM as 4 digits and max duty as 3"""
CTRL_GAIN_MAX = 0.999999
CTRL_RPM_MAX = 9999
CTRL_DUTY_MIN = 20
"""The hub refuses a max duty below CONTROLB_TACHO_CHECK_MIN_PERCENT (20)"""
CTRL_DUTY_MAX = 100


@dataclass
class CtrlSettings:
    """Speed controller B's settings, from the hub's CTRL0 socket. None = not given / unchanged."""

    gain_i: float | None = None
    """Integral gain, 0..CTRL_GAIN_MAX in steps of 1e-6 (BI002000 = 0.002)"""
    rpm: int | None = None
    """Target speed, RPM, 0..CTRL_RPM_MAX (BR0120 = 120). Starts nothing: it is the
    speed of the next Control run or lift move, and live in a Control run in progress
    (bar a run started from the remote hub, whose pot sets its speed). The hub
    refuses it during a lift move."""
    max_duty: int | None = None
    """Max duty cycle, %, CTRL_DUTY_MIN..CTRL_DUTY_MAX (BM050 = 50)"""


# --------------------------------------------------------------------------- direct motor

MotorId = Literal["A", "B"]
"""A channel of the hub's TC78H611FNG bridge - the selector in MOTOR BP030"""
MOTORS_FITTED: tuple[MotorId, ...] = ("B",)
"""The channels that are built. The hub sends selector A to motorB until motorA exists,
so A stays out of this list (and its Direct page section disabled) until then."""
MotorDirection = Literal["forward", "reverse", "disabled"]
"""A bridge direction - the F / R / D in MOTOR BDF / BDR / BDD; disabled = both IN pins
low, the motor coasts"""
MOTOR_DUTY_MAX = 100
"""MOTOR P takes 3 digits; the hub clamps above 100"""


@dataclass
class MotorReadback:
    """MOTOR <id>GP / <id>GD: what the bridge is driven at"""

    duty: int
    """PWM duty cycle, %, 0..MOTOR_DUTY_MAX"""
    direction: MotorDirection


HubMode = Literal["idle", "control", "lift"]
"""The hub's mode (HubApp in the firmware): idle, a Control run (the motor held at the
target speed until stopped) or a lift move."""
HubSource = Literal["pc", "remote", "none"]
"""Who started the run in progress - the PC (this app, or the serial console) or the remote hub"""
CtrlDirection = Literal["forward", "reverse"]
"""A Control run's direction - the F / R in CTRL0 BDF / BDR"""


@dataclass(frozen=True)
class HubState:
    """From the hub's CTRL0 status frame (mode, direction) and BGO (source)."""

    mode: HubMode
    direction: CtrlDirection
    """The run's direction while running, the selected one while idle"""
    source: HubSource | None = None
    """Unknown (None) until read with BGO"""
    run_rpm: int | None = None
    """The run's target speed, RPM, from the status frame: the remote's pot in a run
    the remote started, else the target (BR). None until the first status frame, or
    from firmware that doesn't send it."""


@dataclass
class CtrlReadback:
    """BGA's answer, e.g. 002000.0150.0148, plus BGM, BGD and BGO"""

    gain_i: float
    rpm: int
    max_duty: int
    measured_rpm: int
    """Measured speed, RPM; the hub clamps it at 9999, so 9999 may be a faulty tacho"""
    hub: HubState


HubSocket = Literal["CTRL0", "LIFT0"]
"""The hub's SerLink sockets the app can send raw data to"""

PingResult = Literal["ok", "noSocket", "timeout", "unexpected", "error", "closed"]
"""A SerLink 'S' PING's outcome - as SerLink's PingResult"""


@dataclass
class PingReport:
    result: PingResult
    elapsed_ms: int
    """Milliseconds from queuing the ping to its answer (or timeout)"""
    error: str | None = None
    """Set for 'error'"""


# --------------------------------------------------------------------------- comms config

CommsKind = Literal["sim", "serial", "mqtt"]
CommsStatus = Literal["disconnected", "connecting", "connected", "error"]


@dataclass
class SerialConfig:
    path: str = ""
    baud_rate: int = 115200


@dataclass
class MqttConfig:
    # ControlHubAA26 hub: MQTT_BROKER_IP / MQTT2_TOPIC_UP / MQTT2_TOPIC_DOWN in main_tasks.cpp
    url: str = "mqtt://192.168.0.196:1883"
    telemetry_topic: str = "hub/aa26/serlink/up"
    """Topic the device publishes SerLink frames (telemetry, acks) on"""
    command_topic: str = "hub/aa26/serlink/down"
    """Topic the app publishes SerLink frames (commands, acks) on"""
    username: str = ""
    password: str = ""


@dataclass
class CommsConfig:
    kind: CommsKind = "mqtt"
    serial: SerialConfig = field(default_factory=SerialConfig)
    mqtt: MqttConfig = field(default_factory=MqttConfig)


@dataclass(frozen=True)
class CommsState:
    status: CommsStatus
    kind: CommsKind
    error: str | None = None


@dataclass
class SerialPortInfo:
    path: str
    manufacturer: str = ""
    serial_number: str = ""
    vendor_id: str = ""
    product_id: str = ""


# --------------------------------------------------------------------------- app-kept settings

@dataclass
class ControlHubSettings:
    """The Control Hub settings kept by this app, not the hub (settings.json)."""

    lift_distance: int = 100
    """Lift move distance, edges (1..LIFT_DISTANCE_MAX)"""
    dial_rpm_max: int = 300
    """Top of the dashboard's speed dial, RPM (1..CTRL_RPM_MAX)"""
    set_hub_time_on_launch: bool = True
    """Set the hub's clock (RTC00 S) to this PC's local time once per app run, on the first
    connection to the hub that takes it. The hub has no clock battery, so it loses the
    time when powered off."""


HubClockSetResult = Literal["ok", "refused", "noSocket"]
"""RTC00 S's outcome: taken (S1); refused (S0 - a date the hub can't hold, outside
2000..2099); or no RTC00 socket on the hub (a plain ACK_OK, from firmware without a clock)."""


@dataclass
class DisplaySettings:
    """UI preferences (localStorage in the Electron app)."""

    rpm_max: float = 6000
    current_max: float = 5
    window_sec: int = 10
    """Visible time window on strip charts, s"""
    left_panel_open: bool = True
    dash_control_open: bool = True
    """The Dashboard's Control panel"""


@dataclass(frozen=True)
class MqttLogLine:
    """One line of MQTT traffic, for the MQTT log page."""

    t: float
    """Wall clock, ms since the epoch"""
    dir: Literal["in", "out"]
    """in: from the hub (telemetry topic); out: to the hub (command topic)"""
    topic: str
    line: str


@dataclass(frozen=True)
class DirEntry:
    name: str
    is_dir: bool
    size: int
    mtime_ms: float


def is_finite(v: float) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v)
