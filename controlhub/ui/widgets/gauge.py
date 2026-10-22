"""The dashboard's gauges (components/Gauge.tsx) and the target-speed knob
(components/SpeedDial.tsx), painted with QPainter in the same 200 x 150 view box."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import theme
from . import _geometry as g


class _Scale(QWidget):
    """Shared painting: the track, value arc, ticks and labels, needle and readout."""

    def __init__(self, lo: float, hi: float, label: str, unit: str, color: str, major_ticks: int = 6) -> None:
        super().__init__()
        self.label, self.unit, self.color = label, unit, QColor(color)
        self.major_ticks = major_ticks
        self.lo, self.hi = lo, hi
        self.ticks = g.ticks(lo, hi, major_ticks)
        self.setMinimumSize(140, 105)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_range(self, lo: float, hi: float) -> None:
        if (lo, hi) != (self.lo, self.hi):
            self.lo, self.hi = lo, hi
            self.ticks = g.ticks(lo, hi, self.major_ticks)
            self.update()

    def _begin(self) -> QPainter:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s, ox, oy = g.view_scale(self.width(), self.height())
        p.translate(ox, oy)
        p.scale(s, s)
        return p

    @staticmethod
    def _arc(p: QPainter, r: float, a0: float, a1: float, color: QColor | str, width: float) -> None:
        if a1 - a0 <= 0.01:
            return
        p.setPen(QPen(QColor(color), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        # Qt: 1/16 degrees, counter-clockwise positive; ours run clockwise on screen
        p.drawArc(QRectF(g.CX - r, g.CY - r, 2 * r, 2 * r), int(-a0 * 16), int(-(a1 - a0) * 16))

    def _scale(self, p: QPainter, f: float, ink: QColor) -> None:
        self._arc(p, g.R + 6, g.START, g.START + g.SWEEP, theme.TRACK, 6)
        self._arc(p, g.R + 6, g.START, g.START + f * g.SWEEP, ink, 6)
        sec = QColor(theme.TEXT_2)
        font = QFont(p.font())
        font.setPixelSize(9)  # 8.5 in the SVG; pixel sizes are whole
        p.setFont(font)
        for t in self.ticks:
            p.setPen(QPen(sec, 1.5 if t.major else 0.75))
            p.drawLine(QPointF(t.x0, t.y0), QPointF(t.x1, t.y1))
            if t.label:
                p.drawText(QRectF(t.lx - 16, t.ly - 6, 32, 12), Qt.AlignmentFlag.AlignCenter, t.label)

    @staticmethod
    def _needle(p: QPainter, f: float, ink: QColor, tail: float) -> None:
        p.save()
        p.translate(g.CX, g.CY)
        p.rotate(g.START + f * g.SWEEP)
        p.setPen(QPen(ink, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(-tail, 0), QPointF(g.R - 6, 0))
        p.restore()
        p.setPen(QPen(ink, 2))
        p.setBrush(QColor(theme.PAPER))
        p.drawEllipse(QPointF(g.CX, g.CY), 5, 5)

    def _readout(self, p: QPainter, text: str, color: str) -> None:
        f = QFont(p.font())
        f.setPixelSize(22)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor(color))
        p.drawText(QRectF(g.CX - 70, g.CY + 13, 140, 26), Qt.AlignmentFlag.AlignCenter, text)
        f.setPixelSize(9)
        f.setWeight(QFont.Weight.Normal)
        p.setFont(f)
        p.setPen(QColor(theme.TEXT_2))
        p.drawText(QRectF(g.CX - 70, g.CY + 39, 140, 12), Qt.AlignmentFlag.AlignCenter, f"{self.label} ({self.unit})")


class Gauge(_Scale):
    """Speedometer-style gauge with warn (amber) / danger (red) bands. The needle follows
    every value; the numeric readout refreshes at 10 Hz, which is easier to read."""

    def __init__(self, lo: float, hi: float, label: str, unit: str, color: str, decimals: int = 0,
                 warn: float | None = None, danger: float | None = None, major_ticks: int = 6) -> None:
        super().__init__(lo, hi, label, unit, color, major_ticks)
        self.decimals, self.warn, self.danger = decimals, warn, danger
        self.value: float | None = None
        self._text = "—"
        self._text_timer = QTimer(self, interval=100, timeout=self._refresh_text)
        self._text_timer.start()

    def set_bands(self, hi: float, warn: float | None, danger: float | None) -> None:
        self.warn, self.danger = warn, danger
        self.set_range(self.lo, hi)
        self.update()

    def set_value(self, v: float | None) -> None:
        if v is not None and v != v:  # NaN: the source didn't report it
            v = None
        if v != self.value:
            self.value = v
            self.update()

    def _refresh_text(self) -> None:
        text = "—" if self.value is None else f"{self.value:.{self.decimals}f}"
        if text != self._text:
            self._text = text
            self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = self._begin()
        f = 0.0 if self.value is None else g.frac(self.value, self.lo, self.hi)
        self._scale(p, f, self.color)
        if self.warn is not None:
            end = self.danger if self.danger is not None else self.hi
            self._arc(p, g.R + 1, g.angle(self.warn, self.lo, self.hi), g.angle(end, self.lo, self.hi), theme.WARNING, 2)
        if self.danger is not None:
            self._arc(p, g.R + 1, g.angle(self.danger, self.lo, self.hi), g.START + g.SWEEP, theme.ERROR, 2)
        self._needle(p, f, self.color, 10)
        self._readout(p, self._text, theme.TEXT)
        p.end()


class SpeedDial(_Scale):
    """A rotary knob for a setpoint: drag the pointer round (on the scale - not the
    readout, the centre or the gap), scroll, or use the arrow keys (PageUp / PageDown
    for 10, Home / End). While it is being turned it shows its own value; once the
    hub's value catches up (or a set fails) it shows the hub's again, so it never
    claims a speed the hub did not take.

    mode: "edit"; "disabled" (greyed out); or "readonly" - a meter: drawn in full
    colour, showing `value`, but it can't be turned (a run the remote started)."""

    changed = Signal(int)
    """Whole numbers in lo..hi, as it turns"""

    def __init__(self, hi: int, label: str = "Target", unit: str = "RPM", color: str = theme.SERIES["rpm"],
                 major_ticks: int = 6) -> None:
        super().__init__(0, hi, label, unit, color, major_ticks)
        self.value: int | None = None
        """What the hub holds; None until known"""
        self.mode = "edit"
        self._local: int | None = None
        self._dragging = False
        self._error: object | None = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @property
    def shown(self) -> int | None:
        return self._local if self._local is not None else self.value

    def set_view(self, value: int | None, mode: str, error: object | None = None) -> None:
        """The hub's value, the mode, and the last failed set (a new object per failure)."""
        if error is not None and error is not self._error:
            self._local = None  # a failed set: show the hub's value again
        self._error = error
        if mode != self.mode:
            self.mode = mode
            live = mode == "edit"
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus if live else Qt.FocusPolicy.NoFocus)
            self.setCursor(Qt.CursorShape.PointingHandCursor if live else Qt.CursorShape.ArrowCursor)
            if not live:
                self._dragging = False
                self._local = None
        self.value = value
        if not self._dragging and self._local is not None and value == self._local:
            self._local = None  # the hub agrees
        self.update()

    def _set(self, v: float) -> None:
        nxt = int(min(self.hi, max(self.lo, round(v))))
        if nxt == self.shown:
            return
        self._local = nxt
        self.update()
        self.changed.emit(nxt)

    def _step(self, d: int) -> None:
        # From outside the scale (a target set elsewhere above the dial's max), a step only
        # ever moves towards it - ArrowUp must never cut the speed.
        cur = self.shown if self.shown is not None else self.lo
        if (cur > self.hi and d > 0) or (cur < self.lo and d < 0):
            return
        self._set(cur + d)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if self.mode != "edit" or e.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus()
        # Only a press on the scale itself sets a value - a click on the readout or the
        # centre, or in the gap, must not step a running motor to an end.
        pt = g.point_at(e.position().x(), e.position().y(), self.width(), self.height())
        if not pt or pt[1] < g.GRAB_RADIUS or pt[0] > g.SWEEP:
            return
        self._dragging = True
        self._set(g.value_of(pt[0], self.lo, self.hi))

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._dragging:
            pt = g.point_at(e.position().x(), e.position().y(), self.width(), self.height())
            if pt:
                self._set(g.value_of(pt[0], self.lo, self.hi))

    def mouseReleaseEvent(self, _e) -> None:  # noqa: N802
        self._dragging = False
        # The hub may already agree
        if self._local is not None and self.value == self._local:
            self._local = None
            self.update()

    def wheelEvent(self, e) -> None:  # noqa: N802
        if self.mode == "edit" and e.angleDelta().y():
            self._step(1 if e.angleDelta().y() > 0 else -1)
            e.accept()
        else:
            e.ignore()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if self.mode != "edit":
            return super().keyPressEvent(e)
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

    def focusInEvent(self, e) -> None:  # noqa: N802
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e) -> None:  # noqa: N802
        self.update()
        super().focusOutEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = self._begin()
        ink = QColor(theme.DISABLED_INK) if self.mode == "disabled" else self.color
        shown = self.shown
        f = 0.0 if shown is None else g.frac(shown, self.lo, self.hi)
        self._scale(p, f, ink)
        self._needle(p, f, ink, 0)
        if shown is not None:
            kx, ky = g.polar(g.R + 6, g.START + f * g.SWEEP)
            p.setPen(QPen(ink, 2.5))
            p.setBrush(QColor(theme.PAPER))
            p.drawEllipse(QPointF(kx, ky), 7, 7)
        self._readout(p, "—" if shown is None else str(shown),
                      theme.TEXT_DISABLED if self.mode == "disabled" else theme.TEXT)
        if self.hasFocus() and self.mode == "edit":
            p.setPen(QPen(QColor(theme.PRIMARY), 0.8, Qt.PenStyle.DotLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(g.CX, g.CY), g.R + 12, g.R + 12)
        p.end()
