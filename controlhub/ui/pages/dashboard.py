"""Dashboard: the Control column, three gauges and three strip charts
(pages/DashboardPage.tsx, layouts/DashboardControl.tsx)."""
from __future__ import annotations

import math
from typing import Awaitable, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from ...asyncutil import spawn
from ...context import Context
from ...types import LIFT_DISTANCE_MAX, HubState
from .. import theme
from ..widgets.chrome import Alert, Chip, CmdButton, Lamp, Panel, divider, label
from ..widgets.gauge import Gauge, SpeedDial
from ..widgets.strip_chart import StripChart

GAUGE_HEIGHT = 170


def down_max_edges(distance: int) -> int:
    """Down's max edges: the distance plus 20% headroom, capped at LIFT_DISTANCE_MAX."""
    return min(math.ceil(distance * 1.2), LIFT_DISTANCE_MAX)


DIRECTIONS = [("forward", "Forward"), ("reverse", "Reverse")]
MODE_LABEL = {"idle": "Idle", "control": "Control", "lift": "Lift"}
MODE_ROLE = {"idle": "default", "control": "success", "lift": "info"}
SOURCE_LABEL = {"pc": "PC", "remote": "Remote", "none": ""}


def _combo(items: list[tuple[str, str]]) -> QComboBox:
    c = QComboBox()
    for value, text in items:
        c.addItem(text, value)
    return c


class DashboardControl(Panel):
    """Dashboard's Control panel. The hub (HubApp in the firmware) is in one mode at a
    time - Idle, Control or Lift - and ignores a start unless Idle, so the start buttons
    are only enabled then. Stop ends either.

    Control: a run at the target speed in the chosen direction, until stopped - from here
    or from the remote hub. The dial sets the target speed (0 to Config -> ControlHub's
    dial max): live in a run started here, the next run's while Idle. It is disabled
    during a lift move (the hub fixes a move's speed). During a run the remote started,
    its pot sets the speed, so the dial becomes a read-only meter of that run's target
    (from the status frame).
    Lift: Up/Down moves the lift up by the configured distance, or down to its ground
    sensor (the distance + 20% at most); For/Rev moves it the distance in the direction
    chosen. The hub reports the move's end (Done)."""

    def __init__(self, ctx: Context) -> None:
        self.chip = Chip("—")
        super().__init__("Control", self.chip)
        self.ctx = ctx
        self.setFixedWidth(205)
        self.busy: str | None = None
        b = self.body
        b.setSpacing(9)

        b.addWidget(label("CONTROL", "overline"))
        self.direction = _combo(DIRECTIONS)
        self.direction.activated.connect(
            lambda _i: self._run("direction", lambda: ctx.ctrl.set_direction(self.direction.currentData())))
        b.addWidget(self.direction)
        self.start = CmdButton("Start", "▶")
        self.start.clicked.connect(lambda: self._run("start", ctx.ctrl.start))
        b.addWidget(self.start)
        self.dial = SpeedDial(ctx.control_hub.values.dial_rpm_max)
        self.dial.setFixedHeight(130)
        self.dial.changed.connect(ctx.ctrl.set_rpm_live)
        b.addWidget(self.dial)
        self.rpm_error = label("", "errorText", wrap=True)
        self.rpm_error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b.addWidget(self.rpm_error)

        b.addWidget(divider())
        b.addWidget(label("LIFT", "overline"))
        self.move_mode = _combo([("upDown", "Up/Down"), ("forRev", "For/Rev")])
        self.move_mode.currentIndexChanged.connect(lambda _i: self.refresh())
        b.addWidget(self.move_mode)
        self.modes = QStackedWidget()
        updown = QWidget()
        row = QHBoxLayout(updown)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.up = CmdButton("Up", "↑")
        self.down = CmdButton("Down", "↓")
        self.up.clicked.connect(lambda: self._run("up", lambda: ctx.lift.start(self._distance(), "forward")))
        self.down.clicked.connect(lambda: self._run("down", lambda: ctx.lift.down(down_max_edges(self._distance()))))
        row.addWidget(self.up)
        row.addWidget(self.down)
        forrev = QWidget()
        col = QVBoxLayout(forrev)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(9)
        # Kept between starts, so repeating a move is just Start again.
        self.lift_direction = _combo(DIRECTIONS)
        self.move = CmdButton("Start", "▶")
        self.move.clicked.connect(
            lambda: self._run("move", lambda: ctx.lift.start(self._distance(), self.lift_direction.currentData())))
        col.addWidget(self.lift_direction)
        col.addWidget(self.move)
        self.modes.addWidget(updown)
        self.modes.addWidget(forrev)
        b.addWidget(self.modes)
        self.lift_caption = label("", "caption")
        self.lift_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b.addWidget(self.lift_caption)
        self.done = Lamp("Done")
        b.addWidget(self.done)
        self.progress = label("", "caption")
        self.progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b.addWidget(self.progress)

        b.addWidget(divider())
        self.stop = CmdButton("Stop", "■")
        self.stop.clicked.connect(lambda: self._run("stop", ctx.ctrl.stop))
        b.addWidget(self.stop)
        self.error = Alert()
        b.addWidget(self.error)
        b.addStretch()

        for signal in (ctx.comms.state_changed, ctx.hub.changed, ctx.ctrl.changed, ctx.lift.changed,
                       ctx.control_hub.changed):
            signal.connect(lambda *_: self.refresh())
        self.refresh()

    def _distance(self) -> int:
        return self.ctx.control_hub.values.lift_distance

    def _run(self, which: str, send: Callable[[], Awaitable[None]]) -> None:
        if self.busy:
            return
        self.error.hide()
        self.busy = which
        self.refresh()

        def finish(err: BaseException | None = None) -> None:
            self.busy = None
            if err is not None:
                self.error.show_message(str(err))
            self.refresh()

        spawn(send(), on_error=finish, on_done=lambda _r: finish())

    def refresh(self) -> None:
        ctx = self.ctx
        connected = ctx.comms.state.status == "connected"
        hub = ctx.hub.hub
        rpm = ctx.ctrl.rpm
        idle = hub is not None and hub.mode == "idle"
        # Why the start buttons are disabled, if they are
        blocked = ("Connect first" if not connected else "Waiting for the hub" if hub is None
                   else "The hub is running - stop it first" if not idle else "")
        # Lift::start() on the hub refuses a zero target, silently.
        lift_blocked = blocked or ("The target speed is 0 - turn the dial up first" if rpm == 0 else "")
        # A run the remote started: the dial is a meter of its target (the pot's)
        remote_run = connected and hub is not None and hub.mode == "control" and hub.source == "remote"
        # Why the dial is disabled, if it is
        dial_blocked = ("Connect first" if not connected
                        else "Waiting for the hub" if hub is None or rpm is None
                        else "The speed is fixed during a lift move" if hub.mode == "lift"
                        # Until BGO says who started the run, it may be the remote's
                        else "Waiting for the hub" if hub.mode == "control" and hub.source is None else "")

        self._chip(hub)
        i = 1 if hub is not None and hub.direction == "reverse" else 0
        if self.direction.currentIndex() != i:
            self.direction.setCurrentIndex(i)
        self.direction.setEnabled(not blocked and self.busy is None)

        busy = self.busy
        for btn, which, reason in ((self.start, "start", blocked), (self.up, "up", lift_blocked),
                                   (self.down, "down", lift_blocked), (self.move, "move", lift_blocked),
                                   (self.stop, "stop", "" if connected else "Connect first")):
            btn.set_state(reason, loading=busy == which, busy_elsewhere=busy is not None and busy != which)

        if remote_run:
            self.dial.set_view(hub.run_rpm, "readonly", ctx.ctrl.rpm_error)  # type: ignore[union-attr]
            tip = "The remote's pot sets this run's speed"
        else:
            self.dial.set_view(rpm, "disabled" if dial_blocked else "edit", ctx.ctrl.rpm_error)
            tip = dial_blocked
        self.dial.set_range(0, ctx.control_hub.values.dial_rpm_max)
        if self.dial.toolTip() != tip:
            self.dial.setToolTip(tip)
        err = ctx.ctrl.rpm_error
        show_err = err is not None and not dial_blocked and not remote_run
        self.rpm_error.setText(err.message if show_err else "")  # type: ignore[union-attr]
        self.rpm_error.setVisible(show_err)

        up_down = self.move_mode.currentData() == "upDown"
        self.modes.setCurrentIndex(0 if up_down else 1)
        self.modes.setFixedHeight(self.modes.currentWidget().sizeHint().height())
        d = self._distance()
        self.lift_caption.setText(f"{d} edges" + (f" (Down: {down_max_edges(d)} max)" if up_down else ""))
        self.done.set("Done", theme.SUCCESS if ctx.lift.done else None)
        st = ctx.lift.status
        self.progress.setText(f"{st.travelled} / {st.target} edges" if st else "")
        self.progress.setVisible(st is not None)

    def _chip(self, hub: HubState | None) -> None:
        """The hub's mode, and who started the run: e.g. "Control · Remote"."""
        if hub is None:
            self.chip.set("—", "default")
            return
        source = SOURCE_LABEL[hub.source] if hub.source else ""
        text = f"{MODE_LABEL[hub.mode]} · {source}" if source else MODE_LABEL[hub.mode]
        self.chip.set(text, MODE_ROLE[hub.mode], outlined=hub.mode == "idle")


class DashboardPage(QWidget):
    """The Control panel (toggled from the header) is a fixed-width column on the left;
    gauges across the top, charts filling the rest."""

    def __init__(self, ctx: Context) -> None:
        super().__init__()
        self.ctx = ctx
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self.control = DashboardControl(ctx)
        row.addWidget(self.control)

        right = QVBoxLayout()
        right.setSpacing(12)
        gauges = QHBoxLayout()
        gauges.setSpacing(12)
        d = ctx.display.values
        self.gauges = {
            "rpm": Gauge(0, d.rpm_max, "Speed", "RPM", theme.SERIES["rpm"], warn=d.rpm_max * 0.8, danger=d.rpm_max * 0.93),
            "duty": Gauge(0, 100, "Duty", "%", theme.SERIES["duty"], decimals=1, major_ticks=5),
            "current": Gauge(0, d.current_max, "Current", "A", theme.SERIES["current"], decimals=2,
                             warn=d.current_max * 0.7, danger=d.current_max * 0.9, major_ticks=5),
        }
        for (key, gauge), title in zip(self.gauges.items(), ("Speed", "PWM duty cycle", "Current")):
            p = Panel(title)
            gauge.setFixedHeight(GAUGE_HEIGHT)
            p.body.addWidget(gauge)
            gauges.addWidget(p, 1)
        right.addLayout(gauges)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.charts = {
            "rpm": StripChart(ctx.telemetry, "rpm", "Speed (RPM)", "RPM", window_sec=d.window_sec),
            "duty": StripChart(ctx.telemetry, "duty", "PWM duty (%)", "%", (0, 100), d.window_sec),
            "current": StripChart(ctx.telemetry, "current", "Current (A)", "A", window_sec=d.window_sec),
        }
        for key, pos in (("rpm", (0, 0, 1, 2)), ("duty", (1, 0)), ("current", (1, 1))):
            p = Panel(margins=8)
            p.body.addWidget(self.charts[key])
            grid.addWidget(p, *pos)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        right.addLayout(grid, 1)
        row.addLayout(right, 1)

        ctx.clock.frame.connect(self.redraw)
        ctx.display.changed.connect(self._apply_display)
        self._apply_display()

    def _apply_display(self) -> None:
        d = self.ctx.display.values
        self.control.setVisible(d.dash_control_open)
        self.gauges["rpm"].set_bands(d.rpm_max, d.rpm_max * 0.8, d.rpm_max * 0.93)
        self.gauges["current"].set_bands(d.current_max, d.current_max * 0.7, d.current_max * 0.9)
        for c in self.charts.values():
            c.window_sec = d.window_sec
        self.redraw()

    def redraw(self) -> None:
        if not self.isVisible():
            return
        latest = self.ctx.telemetry.latest
        for key, gauge in self.gauges.items():
            gauge.set_value(latest[key] if latest else None)
        for c in self.charts.values():
            c.redraw()

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self.redraw()
