"""Config -> ControlHub (pages/config/ControlHubConfigPage.tsx).

The controller settings live on the hub (CTRL0: BI gain, BM max duty, BR target speed -
read on connecting, sent on Save) and apply to Control runs and lift moves alike; none
of them starts anything. The dial's max speed and the lift distance are kept by the
app, for the dashboard's speed dial and lift buttons, and so is whether the app sets the
hub's clock when it connects.
"""
from __future__ import annotations

import re

from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QVBoxLayout, QWidget

from ....asyncutil import spawn
from ....context import Context
from ....types import CTRL_DUTY_MAX, CTRL_DUTY_MIN, CTRL_GAIN_MAX, CTRL_GAIN_SCALE, CTRL_RPM_MAX, LIFT_DISTANCE_MAX, \
    CtrlSettings
from ...widgets.chrome import Alert, CmdButton, Field, Panel, label

MODES = [("integral", "Integral"), ("proportional", "Proportional"), ("integralProportional", "Integral - Proportional")]

_GAIN_RE = re.compile(r"^(\d+(\.\d{0,6})?|\.\d{1,6})$")


def parse_gain(text: str) -> float | None:
    """Gain box value, or None unless 0..CTRL_GAIN_MAX with at most 6 decimals (the hub's millionths)."""
    t = text.strip()
    if not _GAIN_RE.match(t):
        return None
    n = float(t)
    return n if n <= CTRL_GAIN_MAX else None


def parse_whole(text: str, lo: int, hi: int) -> int | None:
    """A whole number in lo..hi from a text box, or None."""
    t = text.strip()
    if not t.isdigit() or not t.isascii():
        return None
    n = int(t)
    return n if lo <= n <= hi else None


def same_gain(a: float, b: float) -> bool:
    return round(a * CTRL_GAIN_SCALE) == round(b * CTRL_GAIN_SCALE)


def _num_text(v: float | int | None) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return format(v, ".6f").rstrip("0").rstrip(".") or "0"
    return str(v)


class ControllerPanel(Panel):
    def __init__(self, ctx: Context) -> None:
        super().__init__("Speed controller (Control and Lift)")
        self.ctx = ctx
        self.saving = False
        b = self.body
        b.setSpacing(14)
        mode_box = QVBoxLayout()
        mode_box.setSpacing(3)
        mode_box.addWidget(label("Controller", "caption"))
        self.mode = QComboBox()
        self.mode.setMaximumWidth(300)
        for value, text in MODES:
            self.mode.addItem(text, value)
        self.mode.activated.connect(lambda _i: ctx.ctrl.set_mode(self.mode.currentData()))
        mode_box.addWidget(self.mode)
        b.addLayout(mode_box)
        self.unavailable = label("Not available yet", "caption")
        b.addWidget(self.unavailable)

        self.integral = QWidget()
        il = QVBoxLayout(self.integral)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(12)
        row = QHBoxLayout()
        row.setSpacing(16)
        self.gain = Field("Gain", "integral")
        self.duty = Field("Max duty", "%")
        self.rpm = Field("Target speed", "RPM")
        for f in (self.gain, self.duty, self.rpm):
            row.addWidget(f, 1)
            f.edited.connect(lambda _t: self.refresh())
            f.edit.returnPressed.connect(self._save)
        il.addLayout(row)
        il.addWidget(label("Gain and max duty apply at once, also to a run in progress. The target speed is live in a "
                           "Control run (the dashboard's dial sets it too) but fixed during a lift move - the hub refuses "
                           "it then. A run started from the remote hub takes its speed from the remote's pot instead.",
                           "caption", wrap=True))
        save_row = QHBoxLayout()
        self.save_btn = CmdButton("Save to hub", "💾")
        self.save_btn.setFixedWidth(150)
        self.save_btn.clicked.connect(self._save)
        save_row.addWidget(self.save_btn)
        save_row.addStretch()
        il.addLayout(save_row)
        self.load_error = Alert(closable=False)
        self.error = Alert()
        il.addWidget(self.load_error)
        il.addWidget(self.error)
        b.addWidget(self.integral)

        # Show the hub's values whenever they're read or saved (only when they change, so
        # what you're typing isn't overwritten by an unrelated update).
        self._seen: tuple = (object(), object(), object())
        ctx.ctrl.changed.connect(self.refresh)
        ctx.comms.state_changed.connect(lambda _s: self.refresh())
        self.refresh()

    def _parsed(self):
        c = self.ctx.ctrl
        gain = parse_gain(self.gain.text())
        duty = parse_whole(self.duty.text(), CTRL_DUTY_MIN, CTRL_DUTY_MAX)
        rpm = parse_whole(self.rpm.text(), 0, CTRL_RPM_MAX)
        invalid = (self.gain.text().strip() != "" and gain is None, self.duty.text().strip() != "" and duty is None,
                   self.rpm.text().strip() != "" and rpm is None)
        changed = (gain is not None and (c.gain_i is None or not same_gain(gain, c.gain_i)),
                   duty is not None and duty != c.max_duty, rpm is not None and rpm != c.rpm)
        return gain, duty, rpm, invalid, changed

    def _blocked(self, invalid, changed) -> str:
        """Why Save is disabled, if it is"""
        if self.ctx.comms.state.status != "connected":
            return "Connect first"
        if any(invalid):
            return "Fix the values first"
        if not any(changed):
            return "Nothing changed"
        return ""

    def refresh(self) -> None:
        c = self.ctx.ctrl
        values = (c.gain_i, c.max_duty, c.rpm)
        for field, old, new in zip((self.gain, self.duty, self.rpm), self._seen, values):
            if old is not new and old != new:
                field.set_text(_num_text(new))
        self._seen = values
        i = self.mode.findData(c.mode)
        if self.mode.currentIndex() != i:
            self.mode.setCurrentIndex(i)
        integral = c.mode == "integral"
        self.unavailable.setVisible(not integral)
        self.integral.setVisible(integral)

        connected = self.ctx.comms.state.status == "connected"
        for f in (self.gain, self.duty, self.rpm):
            f.setEnabled(connected and not c.loading)
        _g, _d, _r, invalid, changed = self._parsed()
        self.gain.set_invalid(invalid[0], f"0 to {CTRL_GAIN_MAX}")
        self.duty.set_invalid(invalid[1], f"{CTRL_DUTY_MIN} to {CTRL_DUTY_MAX}")
        self.rpm.set_invalid(invalid[2], f"0 to {CTRL_RPM_MAX}")
        self.save_btn.set_state(self._blocked(invalid, changed), loading=self.saving)
        if c.load_error:
            self.load_error.show_message(f"Couldn't read values: {c.load_error}", "warning",
                                         ("Retry", lambda: spawn(c.load())))
        else:
            self.load_error.hide()

    def _save(self) -> None:
        gain, duty, rpm, invalid, changed = self._parsed()
        if self._blocked(invalid, changed) or self.saving:
            return
        self.error.hide()
        self.saving = True
        self.refresh()

        def done(err: BaseException | None = None) -> None:
            self.saving = False
            if err is not None:
                self.error.show_message(str(err))
            self.refresh()

        spawn(self.ctx.ctrl.save(CtrlSettings(gain_i=gain if changed[0] else None, max_duty=duty if changed[1] else None,
                                              rpm=rpm if changed[2] else None)),
              on_error=done, on_done=lambda _r: done())


class AppSettingPanel(Panel):
    """One whole-number setting kept by the app (settings.json), saved on leaving the box or Enter."""

    def __init__(self, ctx: Context, title: str, field: str, label_text: str, hi: int, help_text: str) -> None:
        super().__init__(title)
        self.ctx = ctx
        self.field = field
        self.hi = hi
        self.input = Field(label_text, f"{help_text} - saved on leaving the box")
        self.input.setMaximumWidth(300)
        self.body.addWidget(self.input)
        self.error = Alert()
        self.body.addWidget(self.error)
        self.input.edited.connect(lambda _t: self._validate())
        self.input.committed.connect(self._save)
        ctx.control_hub.changed.connect(self._load)
        self._load()

    def _current(self) -> int:
        return getattr(self.ctx.control_hub.values, self.field)

    def _load(self) -> None:
        self.input.set_text(str(self._current()))
        self._validate()

    def _validate(self) -> int | None:
        value = parse_whole(self.input.text(), 1, self.hi)
        self.input.set_invalid(value is None, f"1 to {self.hi}")
        return value

    def _save(self) -> None:
        value = self._validate()
        if value is None or value == self._current():
            return
        self.error.hide()
        try:
            self.ctx.control_hub.save(**{self.field: value})
        except (ValueError, OSError) as e:
            self.error.show_message(str(e))


class HubClockPanel(Panel):
    """Whether the app sets the hub's clock (RTC00 S) to this PC's local time once per run,
    on the first connection the hub answers - see CommsHub._hub_clock_loop. Saved at once
    (settings.json)."""

    def __init__(self, ctx: Context) -> None:
        super().__init__("Hub clock")
        self.ctx = ctx
        self.enabled = QCheckBox("Set hub date time on app launch")
        self.enabled.toggled.connect(self._save)
        self.body.addWidget(self.enabled)
        self.body.addWidget(label("Sets the hub's clock to this PC's local time once each time the app runs, on the "
                                  "first connection the hub answers. The hub has no clock battery, so it loses the "
                                  "time when powered off (a reset keeps it). The hub stamps its SD card files with "
                                  "this clock. The setting is read at the run's first connection to the hub.",
                                  "caption", wrap=True))
        self.error = Alert()
        self.body.addWidget(self.error)
        ctx.control_hub.changed.connect(self._load)
        self._load()

    def _load(self) -> None:
        self.enabled.blockSignals(True)
        self.enabled.setChecked(self.ctx.control_hub.values.set_hub_time_on_launch)
        self.enabled.blockSignals(False)

    def _save(self, checked: bool) -> None:
        if checked == self.ctx.control_hub.values.set_hub_time_on_launch:
            return
        self.error.hide()
        try:
            self.ctx.control_hub.save(set_hub_time_on_launch=checked)
        except (ValueError, OSError) as e:
            self.error.show_message(str(e))
            self._load()


class ControlHubConfigPage(QWidget):
    def __init__(self, ctx: Context) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        lay.addWidget(ControllerPanel(ctx))
        lay.addWidget(AppSettingPanel(ctx, "Speed dial", "dial_rpm_max", "Dial max speed", CTRL_RPM_MAX,
                                      "RPM - the top of the dashboard's speed dial"))
        lay.addWidget(AppSettingPanel(ctx, "Lift", "lift_distance", "Target distance", LIFT_DISTANCE_MAX,
                                      "tacho edges (2 per revolution)"))
        lay.addWidget(HubClockPanel(ctx))
