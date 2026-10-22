"""Direct (pages/DirectPage.tsx): the hub's motors driven open loop through its MOTOR
socket (P and D) - a duty dial and a bridge direction per motor, with no speed
controller. The hub takes them only while idle. A run or lift move started meanwhile
takes the motor over, and leaves it at 0% with no direction when it ends. The hub sends
no status frames while idle, so the Dashboard does not show a motor driven from here."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ...asyncutil import spawn
from ...context import Context
from ...types import MOTOR_DUTY_MAX, MOTORS_FITTED, MotorDirection, MotorId
from .. import theme
from ..widgets.chrome import Panel, button, label
from ..widgets.gauge import SpeedDial

MOTOR_IDS: tuple[MotorId, ...] = ("A", "B")
DIAL_HEIGHT = 160


class MotorSection(Panel):
    """One motor: its direction and its duty dial. A motor that isn't fitted
    (MOTORS_FITTED) is drawn the same, but disabled - the hub would send its commands to
    motorB."""

    def __init__(self, ctx: Context, motor: MotorId) -> None:
        super().__init__(f"Motor {motor}")
        self.ctx = ctx
        self.motor = motor
        self.content = QWidget()
        col = QVBoxLayout(self.content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(9)
        row = QHBoxLayout()
        row.setSpacing(0)
        self.buttons: dict[MotorDirection, object] = {}
        for direction, text in (("forward", "Forward"), ("reverse", "Reverse")):
            b = button(text, variant="outlined")
            b.setCheckable(True)
            b.clicked.connect(lambda _c=False, d=direction: self._on_direction(d))
            row.addWidget(b, 1)
            self.buttons[direction] = b
        col.addLayout(row)
        self.coast = label("", "caption")
        self.coast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(self.coast)
        self.dial = SpeedDial(MOTOR_DUTY_MAX, "Duty", "%", theme.SERIES["duty"], major_ticks=5)
        self.dial.setFixedHeight(DIAL_HEIGHT)
        self.dial.changed.connect(lambda v: ctx.direct.set_duty_live(motor, v))
        col.addWidget(self.dial)
        self.error = label("", "errorText", wrap=True)
        self.error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(self.error)
        col.addStretch()
        self.body.addWidget(self.content)

        for signal in (ctx.comms.state_changed, ctx.hub.changed, ctx.direct.changed):
            signal.connect(lambda *_: self.refresh())
        self.refresh()

    def _on_direction(self, direction: MotorDirection) -> None:
        """Pressing the pressed one again lets the motor coast (D)."""
        current = self.ctx.direct.motors[self.motor].direction
        spawn(self.ctx.direct.set_direction(self.motor, "disabled" if current == direction else direction))
        self.refresh()  # the buttons show what the hub holds, not the click

    def refresh(self) -> None:
        ctx = self.ctx
        comms = ctx.comms.state
        hub = ctx.hub.hub
        m = ctx.direct.motors[self.motor]
        # Why the section is disabled, if it is
        blocked = (f"Motor {self.motor} is not fitted" if self.motor not in MOTORS_FITTED
                   else "Connect first" if comms.status != "connected"
                   else "Needs a serial or MQTT connection" if comms.kind == "sim"
                   else "Waiting for the hub" if hub is None or m.duty is None
                   else "The hub is running - stop it first" if hub.mode != "idle" else "")

        # Neither button is pressed while the bridge has no direction (disabled).
        for direction, b in self.buttons.items():
            b.setChecked(m.direction == direction)  # type: ignore[attr-defined]
            b.setEnabled(not blocked)  # type: ignore[attr-defined]
        self.coast.setText("No direction - the motor coasts" if m.direction == "disabled" else "")
        self.dial.set_view(m.duty, "disabled" if blocked else "edit", m.duty_error)
        if self.content.toolTip() != blocked:
            self.content.setToolTip(blocked)
        msg = m.duty_error.message if m.duty_error is not None else m.error
        show = bool(msg) and not blocked
        self.error.setText(msg if show else "")  # type: ignore[arg-type]
        self.error.setVisible(show)


class DirectPage(QWidget):
    def __init__(self, ctx: Context) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = Panel("Motor")
        panel.setMaximumWidth(720)
        row = QHBoxLayout()
        row.setSpacing(12)
        for motor in MOTOR_IDS:
            row.addWidget(MotorSection(ctx, motor), 1)
        panel.body.addLayout(row)
        outer.addWidget(panel, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        outer.addStretch()
