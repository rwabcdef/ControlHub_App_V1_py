"""Candidate 1: PySide6 + Qt Widgets, gauges painted with QPainter, charts by pyqtgraph.

Run:  .venv\\Scripts\\python qt_widgets_demo.py
"""
from __future__ import annotations

import sys

import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QSizePolicy, QTabBar, QVBoxLayout, QWidget,
)

from common import geometry as g
from common.sim import CURRENT_MAX, DIAL_RPM_MAX, RPM_MAX, SCENARIOS, WINDOW_SEC, FpsMeter, HubSim

STYLE = f"""
QWidget {{ background: {g.BG}; color: {g.TEXT}; font-family: "Segoe UI"; font-size: 13px; }}
QFrame#panel {{ background: {g.PAPER}; border: 1px solid {g.DIVIDER}; border-radius: 6px; }}
QFrame#panel QLabel, QWidget#clear {{ background: transparent; }}
QLabel#panelTitle {{ color: {g.TEXT_2}; font-weight: 600; }}
QLabel#overline {{ color: {g.TEXT_2}; font-size: 11px; letter-spacing: 1px; }}
QLabel#caption {{ color: {g.TEXT_2}; font-size: 11px; }}
QPushButton {{ background: {g.PRIMARY}; color: #0b1a22; border: none; border-radius: 4px;
  padding: 5px 10px; font-weight: 600; }}
QPushButton:hover {{ background: #81d4fa; }}
QPushButton:disabled {{ background: #2a3038; color: {g.TEXT_DISABLED}; }}
QPushButton#ghost {{ background: transparent; color: {g.PRIMARY}; border: 1px solid #2f5d73; }}
QComboBox {{ background: transparent; border: 1px solid {g.DIVIDER}; border-radius: 4px; padding: 4px 8px; }}
QComboBox:disabled {{ color: {g.TEXT_DISABLED}; }}
QComboBox QAbstractItemView {{ background: {g.PAPER}; selection-background-color: #1f3a48; }}
QTabBar::tab {{ background: transparent; color: {g.TEXT_2}; padding: 8px 14px; border: none; }}
QTabBar::tab:selected {{ color: {g.PRIMARY}; border-bottom: 2px solid {g.PRIMARY}; }}
QToolTip {{ background: #2b313a; color: {g.TEXT}; border: none; padding: 4px; }}
"""


# --------------------------------------------------------------------------- gauges
class _ScalePainter(QWidget):
    """Shared painting for the gauge and the dial: the 200 x 150 view box, scaled to fit."""

    def __init__(self, lo: float, hi: float, label: str, unit: str, color: str, major_ticks: int = 6):
        super().__init__()
        self.lo, self.hi, self.label, self.unit = lo, hi, label, unit
        self.color = QColor(color)
        self.ticks = g.ticks(lo, hi, major_ticks)
        self.setMinimumSize(160, 120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def _begin(self) -> QPainter:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s, ox, oy = g.view_scale(self.width(), self.height())
        p.translate(ox, oy)
        p.scale(s, s)
        return p

    @staticmethod
    def _arc(p: QPainter, r: float, a0: float, a1: float, color: QColor, width: float, cap=Qt.PenCapStyle.FlatCap):
        if a1 <= a0:
            return
        p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, cap))
        # Qt: degrees * 16, counter-clockwise positive; ours are clockwise on screen
        p.drawArc(QRectF(g.CX - r, g.CY - r, 2 * r, 2 * r), int(-a0 * 16), int(-(a1 - a0) * 16))

    def _scale(self, p: QPainter, f: float, ink: QColor):
        self._arc(p, g.R + 6, g.START, g.START + g.SWEEP, QColor(g.TRACK), 6)
        self._arc(p, g.R + 6, g.START, g.START + f * g.SWEEP, ink, 6)
        sec = QColor(g.TEXT_2)
        p.setFont(QFont("Segoe UI", 1))
        font = p.font()
        font.setPointSizeF(6.4)
        p.setFont(font)
        for t in self.ticks:
            p.setPen(QPen(sec, 1.5 if t.major else 0.75))
            p.drawLine(QPointF(t.x0, t.y0), QPointF(t.x1, t.y1))
            if t.label:
                p.drawText(QRectF(t.lx - 15, t.ly - 6, 30, 12), Qt.AlignmentFlag.AlignCenter, t.label)

    def _needle(self, p: QPainter, f: float, ink: QColor, tail: float):
        a = g.START + f * g.SWEEP
        p.save()
        p.translate(g.CX, g.CY)
        p.rotate(a)
        p.setPen(QPen(ink, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(-tail, 0), QPointF(g.R - 6, 0))
        p.restore()
        p.setPen(QPen(ink, 2))
        p.setBrush(QColor(g.PAPER))
        p.drawEllipse(QPointF(g.CX, g.CY), 5, 5)

    def _readout(self, p: QPainter, text: str, color: QColor):
        f = QFont("Segoe UI")
        f.setPointSizeF(16)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(color)
        p.drawText(QRectF(g.CX - 60, g.CY + 14, 120, 24), Qt.AlignmentFlag.AlignCenter, text)
        f.setPointSizeF(6.8)
        f.setWeight(QFont.Weight.Normal)
        p.setFont(f)
        p.setPen(QColor(g.TEXT_2))
        p.drawText(QRectF(g.CX - 60, g.CY + 38, 120, 12), Qt.AlignmentFlag.AlignCenter, f"{self.label} ({self.unit})")


class Gauge(_ScalePainter):
    """Gauge.tsx: speedometer with warn / danger bands. The readout updates at 10 Hz."""

    def __init__(self, lo, hi, label, unit, color, decimals=0, warn=None, danger=None, major_ticks=6):
        super().__init__(lo, hi, label, unit, color, major_ticks)
        self.decimals, self.warn, self.danger = decimals, warn, danger
        self.value: float | None = None
        self.text = "—"
        self._text_timer = QTimer(self, interval=100, timeout=self._refresh_text)
        self._text_timer.start()

    def set_value(self, v: float | None):
        self.value = v
        self.update()

    def _refresh_text(self):
        self.text = "—" if self.value is None else f"{self.value:.{self.decimals}f}"

    def paintEvent(self, _):
        p = self._begin()
        f = 0.0 if self.value is None else g.frac(self.value, self.lo, self.hi)
        self._scale(p, f, self.color)
        if self.warn is not None:
            self._arc(p, g.R + 1, g.angle(self.warn, self.lo, self.hi),
                      g.angle(self.danger if self.danger is not None else self.hi, self.lo, self.hi), QColor(g.WARN), 2)
        if self.danger is not None:
            self._arc(p, g.R + 1, g.angle(self.danger, self.lo, self.hi), g.START + g.SWEEP, QColor(g.DANGER), 2)
        self._needle(p, f, self.color, 10)
        self._readout(p, self.text, QColor(g.TEXT))
        p.end()


class SpeedDial(_ScalePainter):
    """SpeedDial.tsx: a setpoint knob. state: 'edit', 'readonly' (a meter) or 'disabled'."""

    changed = Signal(int)

    def __init__(self, lo, hi, label, unit, color):
        super().__init__(lo, hi, label, unit, color)
        self.value: int | None = None
        self.state = "edit"
        self._drag = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_view(self, value: int | None, state: str, tooltip: str):
        if state != "edit":
            self._drag = False
        if (value, state) != (self.value, self.state):
            self.value, self.state = value, state
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus if state == "edit" else Qt.FocusPolicy.NoFocus)
            self.setCursor(Qt.CursorShape.PointingHandCursor if state == "edit" else Qt.CursorShape.ArrowCursor)
            self.update()
        if self.toolTip() != tooltip:
            self.setToolTip(tooltip)

    def _set(self, v: float):
        nv = int(min(self.hi, max(self.lo, round(v))))
        if nv != self.value:
            self.value = nv
            self.update()
            self.changed.emit(nv)

    def _step(self, d: int):
        cur = self.value if self.value is not None else self.lo
        if (cur > self.hi and d > 0) or (cur < self.lo and d < 0):
            return
        self._set(cur + d)

    def mousePressEvent(self, e):
        if self.state != "edit" or e.button() != Qt.MouseButton.LeftButton:
            return
        pt = g.point_at(e.position().x(), e.position().y(), self.width(), self.height())
        if not pt or pt[1] < g.GRAB_RADIUS or pt[0] > g.SWEEP:
            return
        self._drag = True
        self._set(g.value_of(pt[0], self.lo, self.hi))

    def mouseMoveEvent(self, e):
        if self._drag:
            pt = g.point_at(e.position().x(), e.position().y(), self.width(), self.height())
            if pt:
                self._set(g.value_of(pt[0], self.lo, self.hi))

    def mouseReleaseEvent(self, _):
        self._drag = False

    def wheelEvent(self, e):
        if self.state == "edit" and e.angleDelta().y():
            self._step(1 if e.angleDelta().y() > 0 else -1)
            e.accept()

    def keyPressEvent(self, e):
        if self.state != "edit":
            return
        k = e.key()
        steps = {Qt.Key.Key_Up: 1, Qt.Key.Key_Right: 1, Qt.Key.Key_Down: -1, Qt.Key.Key_Left: -1,
                 Qt.Key.Key_PageUp: 10, Qt.Key.Key_PageDown: -10}
        if k in steps:
            self._step(steps[k])
        elif k == Qt.Key.Key_Home:
            self._set(self.lo)
        elif k == Qt.Key.Key_End:
            self._set(self.hi)
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _):
        p = self._begin()
        ink = QColor(g.DISABLED_INK) if self.state == "disabled" else self.color
        f = 0.0 if self.value is None else g.frac(self.value, self.lo, self.hi)
        self._scale(p, f, ink)
        self._needle(p, f, ink, 0)
        if self.value is not None:
            kx, ky = g.polar(g.R + 6, g.START + f * g.SWEEP)
            p.setPen(QPen(ink, 2.5))
            p.setBrush(QColor(g.PAPER))
            p.drawEllipse(QPointF(kx, ky), 7, 7)
        self._readout(p, "—" if self.value is None else str(self.value),
                      QColor(g.TEXT_DISABLED if self.state == "disabled" else g.TEXT))
        if self.hasFocus():
            p.setPen(QPen(QColor(g.PRIMARY), 0.8, Qt.PenStyle.DotLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(g.CX, g.CY), g.R + 12, g.R + 12)
        p.end()


# --------------------------------------------------------------------------- chrome
def panel(title: str | None = None, action: QWidget | None = None) -> tuple[QFrame, QVBoxLayout]:
    """Panel.tsx: an outlined card with an optional title row."""
    frame = QFrame(objectName="panel")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(12, 10, 12, 12)
    lay.setSpacing(8)
    if title or action:
        row = QHBoxLayout()
        row.addWidget(QLabel(title or "", objectName="panelTitle"), 1)
        if action:
            row.addWidget(action)
        lay.addLayout(row)
    return frame, lay


class Chip(QLabel):
    COLORS = {"default": (g.TEXT_2, g.DIVIDER, "transparent"), "success": ("#0d1f0e", g.SUCCESS, g.SUCCESS),
              "info": ("#06222c", "#29b6f6", "#29b6f6")}

    def set(self, text: str, role: str):
        fg, border, bg = self.COLORS[role]
        self.setText(text)
        self.setStyleSheet(f"QLabel {{ color: {fg}; background: {bg}; border: 1px solid {border};"
                           f" border-radius: 11px; padding: 2px 9px; font-size: 12px; }}")


class DoneLamp(QFrame):
    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.addStretch()
        self.dot = QLabel()
        self.dot.setFixedSize(12, 12)
        self.text = QLabel("Done")
        lay.addWidget(self.dot)
        lay.addWidget(self.text)
        lay.addStretch()
        self._done = None
        self.set(False)

    def set(self, done: bool):
        if done == self._done:
            return
        self._done = done
        c = g.SUCCESS if done else g.DIVIDER
        self.setStyleSheet(f"DoneLamp {{ background: transparent; border: 1px solid {c}; border-radius: 6px; }}")
        self.dot.setStyleSheet(f"background: {g.SUCCESS if done else '#3a4049'}; border-radius: 6px;"
                               + (f"border: 2px solid #a5d6a7;" if done else ""))
        self.text.setStyleSheet(f"color: {g.SUCCESS if done else g.TEXT_DISABLED}; font-weight: 600;")


class BusyButton(QPushButton):
    """A MUI-style button: a spinner glyph replaces the label while its command is in flight."""

    SPIN = "◐◓◑◒"

    def __init__(self, label: str, icon: str, onclick, which: str, ghost=False):
        super().__init__(f"{icon}  {label}")
        self.label, self.icon_text, self.which, self._spin = label, icon, which, 0
        if ghost:
            self.setObjectName("ghost")
        self.clicked.connect(onclick)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def refresh(self, busy: str | None, reason: str):
        if busy == self.which:
            self._spin = (self._spin + 1) % 4
            self.setText(f"{self.SPIN[self._spin]}  {self.label}")
        else:
            self.setText(f"{self.icon_text}  {self.label}")
        self.setEnabled(not reason and (busy is None or busy == self.which))
        if self.toolTip() != reason:
            self.setToolTip(reason)


# --------------------------------------------------------------------------- the screen
class ControlPanel(QFrame):
    """DashboardControl.tsx"""

    def __init__(self, sim: HubSim):
        super().__init__()
        self.sim = sim
        self.chip = Chip()
        frame, lay = panel("Control", self.chip)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)
        self.setFixedWidth(200)

        lay.addWidget(QLabel("CONTROL", objectName="overline"))
        self.direction = QComboBox()
        self.direction.addItems(["Forward", "Reverse"])
        self.direction.activated.connect(lambda i: sim.set_direction(["forward", "reverse"][i]))
        lay.addWidget(self.direction)
        self.start = BusyButton("Start", "▶", sim.start, "start")
        lay.addWidget(self.start)
        self.dial = SpeedDial(0, DIAL_RPM_MAX, "Target", "RPM", g.SERIES["rpm"])
        self.dial.setFixedHeight(140)
        self.dial.changed.connect(sim.set_rpm)
        lay.addWidget(self.dial)

        lay.addWidget(self._divider())
        lay.addWidget(QLabel("LIFT", objectName="overline"))
        self.move_mode = QComboBox()
        self.move_mode.addItems(["Up/Down", "For/Rev"])
        self.move_mode.currentIndexChanged.connect(self._move_mode)
        lay.addWidget(self.move_mode)
        self.updown = QWidget(objectName="clear")
        ud = QHBoxLayout(self.updown)
        ud.setContentsMargins(0, 0, 0, 0)
        self.up = BusyButton("Up", "↑", sim.lift_up, "up")
        self.down = BusyButton("Down", "↓", sim.lift_down, "down")
        ud.addWidget(self.up)
        ud.addWidget(self.down)
        lay.addWidget(self.updown)
        self.lift_dir = QComboBox()
        self.lift_dir.addItems(["Forward", "Reverse"])
        self.lift_dir.currentIndexChanged.connect(lambda i: setattr(sim, "lift_direction", ["forward", "reverse"][i]))
        self.move = BusyButton("Start", "▶", sim.lift_move, "move")
        lay.addWidget(self.lift_dir)
        lay.addWidget(self.move)
        self.lift_caption = QLabel(objectName="caption", alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lift_caption)
        self.done = DoneLamp()
        lay.addWidget(self.done)
        self.progress = QLabel(objectName="caption", alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.progress)
        lay.addWidget(self._divider())
        self.stop = BusyButton("Stop", "■", sim.stop, "stop")
        lay.addWidget(self.stop)
        lay.addStretch()
        self._move_mode(0)

    @staticmethod
    def _divider() -> QFrame:
        d = QFrame()
        d.setFixedHeight(1)
        d.setStyleSheet(f"background: {g.DIVIDER};")
        return d

    def _move_mode(self, i: int):
        self.sim.move_mode = ["upDown", "forRev"][i]
        self.updown.setVisible(i == 0)
        self.lift_dir.setVisible(i == 1)
        self.move.setVisible(i == 1)

    def refresh(self):
        s = self.sim
        self.chip.set(*s.mode_chip())
        self.direction.setCurrentIndex(0 if s.direction == "forward" else 1)
        self.direction.setEnabled(not s.start_blocked() and s.busy is None)
        self.start.refresh(s.busy, s.start_blocked())
        for b in (self.up, self.down, self.move):
            b.refresh(s.busy, s.lift_blocked())
        self.stop.refresh(s.busy, "")
        d = s.dial()
        self.dial.set_view(d.value, d.state, d.tooltip)
        self.lift_caption.setText(s.lift_caption())
        self.done.set(s.done)
        self.progress.setText(s.lift_progress())


def strip_chart(field: str, label: str, y_label: str, y_range=None) -> tuple[QFrame, pg.PlotDataItem, pg.PlotWidget]:
    frame, lay = panel()
    legend = QHBoxLayout()
    sw = QLabel()
    sw.setFixedSize(12, 3)
    sw.setStyleSheet(f"background: {g.SERIES[field]}; border-radius: 1px;")
    legend.addWidget(sw)
    legend.addWidget(QLabel(label, objectName="caption"))
    legend.addStretch()
    tl = QLabel("t (s)", objectName="caption")
    legend.addWidget(tl)
    lay.addLayout(legend)
    pw = pg.PlotWidget(background=g.PAPER)
    pw.setMenuEnabled(False)
    pw.setMouseEnabled(False, False)
    pw.hideButtons()
    pi = pw.getPlotItem()
    pi.showGrid(x=True, y=True, alpha=0.18)
    for ax in ("left", "bottom"):
        a = pi.getAxis(ax)
        a.setPen(pg.mkPen(g.DIVIDER))
        a.setTextPen(pg.mkPen(g.TEXT_2))
    pi.setLabel("left", y_label, color=g.TEXT_2)
    if y_range:
        pi.setYRange(*y_range, padding=0)
    else:
        pi.enableAutoRange("y", True)
    curve = pw.plot(pen=pg.mkPen(g.SERIES[field], width=1.5))
    curve.setClipToView(True)
    lay.addWidget(pw, 1)
    return frame, curve, pw


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ControlHub AA26 — Qt Widgets demo")
        self.resize(1280, 800)
        self.sim = HubSim()
        self.fps = FpsMeter()
        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Header (MainLayout.tsx), plus the demo's own sim controls
        header = QWidget()
        header.setStyleSheet(f"border-bottom: 1px solid {g.DIVIDER};")
        h = QHBoxLayout(header)
        h.setContentsMargins(12, 6, 12, 6)
        title = QLabel(f"<b>ControlHub</b> <span style='color:{g.TEXT_2}'>AA26</span>")
        title.setStyleSheet("font-size: 16px; border: none;")
        h.addWidget(title)
        h.addStretch()
        sim_lbl = QLabel("Sim:")
        sim_lbl.setStyleSheet(f"color: {g.TEXT_2}; border: none;")
        h.addWidget(sim_lbl)
        self.scenario = QComboBox()
        self.scenario.addItems(SCENARIOS)
        self.scenario.activated.connect(lambda i: self.sim.set_scenario(SCENARIOS[i]))
        h.addWidget(self.scenario)
        remote = QPushButton("Remote button 1", objectName="ghost")
        remote.setToolTip("Start / stop a run as the remote hub would")
        remote.clicked.connect(self.sim.remote_button)
        h.addWidget(remote)
        self.fps_label = QLabel()
        self.fps_label.setStyleSheet(f"color: {g.TEXT_2}; border: none; min-width: 120px;")
        h.addWidget(self.fps_label)
        conn = Chip()
        conn.set("SIM · connected", "success")
        h.addWidget(conn)
        v.addWidget(header)

        nav = QWidget()
        nav.setStyleSheet(f"border-bottom: 1px solid {g.DIVIDER};")
        nl = QHBoxLayout(nav)
        nl.setContentsMargins(8, 0, 8, 0)
        tabs = QTabBar()
        tabs.setExpanding(False)
        tabs.setDrawBase(False)
        for t in ("Dashboard", "Config", "MQTT log", "Files", "Dev"):
            tabs.addTab(t)
        tabs.setStyleSheet("border: none;")
        nl.addWidget(tabs)
        nl.addStretch()
        v.addWidget(nav)

        # Dashboard (DashboardPage.tsx)
        body = QWidget()
        b = QHBoxLayout(body)
        b.setContentsMargins(12, 12, 12, 12)
        b.setSpacing(12)
        self.control = ControlPanel(self.sim)
        b.addWidget(self.control)
        right = QVBoxLayout()
        right.setSpacing(12)
        gauges = QHBoxLayout()
        gauges.setSpacing(12)
        self.gauges = {
            "rpm": Gauge(0, RPM_MAX, "Speed", "RPM", g.SERIES["rpm"], warn=RPM_MAX * 0.8, danger=RPM_MAX * 0.93),
            "duty": Gauge(0, 100, "Duty", "%", g.SERIES["duty"], decimals=1, major_ticks=5),
            "current": Gauge(0, CURRENT_MAX, "Current", "A", g.SERIES["current"], decimals=2,
                             warn=CURRENT_MAX * 0.7, danger=CURRENT_MAX * 0.9, major_ticks=5),
        }
        for (k, gauge), t in zip(self.gauges.items(), ("Speed", "PWM duty cycle", "Current")):
            f, lay = panel(t)
            gauge.setFixedHeight(170)
            lay.addWidget(gauge)
            gauges.addWidget(f)
        right.addLayout(gauges)
        charts = QGridLayout()
        charts.setSpacing(12)
        self.charts = {}
        for field, lbl, yl, yr, pos in (("rpm", "Speed (RPM)", "RPM", None, (0, 0, 1, 2)),
                                        ("duty", "PWM duty (%)", "%", (0, 100), (1, 0, 1, 1)),
                                        ("current", "Current (A)", "A", None, (1, 1, 1, 1))):
            f, curve, pw = strip_chart(field, lbl, yl, yr)
            self.charts[field] = (curve, pw)
            charts.addWidget(f, *pos)
        right.addLayout(charts, 1)
        b.addLayout(right, 1)
        v.addWidget(body, 1)

        self._ticks = 0
        self.timer = QTimer(self, interval=16, timeout=self.frame)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.start()

    def frame(self):
        self.fps.frame()
        self.sim.step()
        for k, gauge in self.gauges.items():
            gauge.set_value(self.sim.latest(k))
        t_max = max(WINDOW_SEC, self.sim.now())
        for k, (curve, pw) in self.charts.items():
            t, y = self.sim.history(k)
            curve.setData(t, y)
            pw.setXRange(t_max - WINDOW_SEC, t_max, padding=0)
        self._ticks += 1
        if self._ticks % 6 == 0:  # controls at ~10 Hz
            self.control.refresh()
            self.fps_label.setText(self.fps.text())
            if self.sim.scenario != SCENARIOS[self.scenario.currentIndex()]:
                self.scenario.setCurrentIndex(SCENARIOS.index(self.sim.scenario))


def main():
    pg.setConfigOptions(antialias=True)
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    w = Window()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
