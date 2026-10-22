"""Config -> Display (pages/config/DisplayConfigPage.tsx): gauge full scales and the
charts' time window. Applied on leaving a box / moving the slider, persisted."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QSlider, QVBoxLayout, QWidget

from ....context import Context
from ...widgets.chrome import Field, Panel, button, label


def _num(text: str, fallback: float) -> float:
    try:
        v = float(text)
    except ValueError:
        return fallback
    return v if v > 0 else fallback


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


class DisplayConfigPage(QWidget):
    def __init__(self, ctx: Context) -> None:
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        ranges = Panel("Gauge ranges")
        row = QHBoxLayout()
        row.setSpacing(16)
        self.rpm_max = Field("Speed full scale (RPM)")
        self.current_max = Field("Current full scale (A)")
        row.addWidget(self.rpm_max, 1)
        row.addWidget(self.current_max, 1)
        ranges.body.addLayout(row)
        self.rpm_max.committed.connect(
            lambda: ctx.display.set(rpm_max=_num(self.rpm_max.text(), ctx.display.values.rpm_max)))
        self.current_max.committed.connect(
            lambda: ctx.display.set(current_max=_num(self.current_max.text(), ctx.display.values.current_max)))
        lay.addWidget(ranges)

        charts = Panel("Charts")
        self.window_label = label("")
        charts.body.addWidget(self.window_label)
        self.window = QSlider(Qt.Orientation.Horizontal)
        self.window.setRange(1, 60)
        self.window.setMaximumWidth(400)
        self.window.valueChanged.connect(lambda v: v != ctx.display.values.window_sec and ctx.display.set(window_sec=v))
        charts.body.addWidget(self.window)
        lay.addWidget(charts)

        reset = QHBoxLayout()
        reset.addWidget(button("Reset to defaults", ctx.display.reset, "outlined"))
        reset.addStretch()
        lay.addLayout(reset)

        ctx.display.changed.connect(self._load)
        self._load()

    def _load(self) -> None:
        d = self.ctx.display.values
        self.rpm_max.set_text(_fmt(d.rpm_max))
        self.current_max.set_text(_fmt(d.current_max))
        self.window_label.setText(f"Visible time window: {d.window_sec} s")
        if self.window.value() != d.window_sec:
            self.window.setValue(d.window_sec)
