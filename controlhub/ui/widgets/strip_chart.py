"""Scrolling time-series chart (components/StripChart.tsx, uPlot there; pyqtgraph here).

The x axis is the last `window_sec` seconds, ending at the newest sample. Only the
samples inside the window are handed to pyqtgraph each frame, so a full 60,000-point
buffer costs no more to draw than a short one. NaN (a value the source didn't report)
is drawn as a gap.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...state.telemetry import TelemetryStore
from ...types import MotorField
from .. import theme
from .chrome import label

# exitCleanup off: the app deletes its Qt objects itself on exit (QApplication.shutdown() in
# __main__), and pyqtgraph's atexit hook would then touch objects already gone.
pg.setConfigOptions(antialias=True, foreground=theme.TEXT_2, background=theme.PAPER, exitCleanup=False)


class StripChart(QWidget):
    def __init__(self, store: TelemetryStore, field: MotorField, series_label: str, y_label: str,
                 y_range: tuple[float, float] | None = None, window_sec: float = 10) -> None:
        super().__init__()
        self._store = store
        self._field = field
        self.window_sec = window_sec
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        legend = QHBoxLayout()
        legend.setContentsMargins(8, 0, 4, 0)
        swatch = QLabel()
        swatch.setFixedSize(12, 3)
        swatch.setStyleSheet(f"background: {theme.SERIES[field]}; border-radius: 1px;")
        legend.addWidget(swatch)
        legend.addWidget(label(series_label, "caption"))
        legend.addStretch()
        t_label = label("t (s)", "caption")
        t_label.setStyleSheet(f"color: {theme.TEXT_DISABLED};")
        legend.addWidget(t_label)
        lay.addLayout(legend)

        self.plot = pg.PlotWidget(background=theme.PAPER)
        self.plot.setMenuEnabled(False)
        self.plot.setMouseEnabled(False, False)
        self.plot.hideButtons()
        pi = self.plot.getPlotItem()
        pi.showGrid(x=True, y=True, alpha=0.25)
        for name in ("left", "bottom"):
            ax = pi.getAxis(name)
            ax.setPen(pg.mkPen(theme.DIVIDER))
            ax.setTextPen(pg.mkPen(theme.TEXT_2))
        pi.getAxis("left").setWidth(50)
        pi.setLabel("left", y_label, color=theme.TEXT_2)
        if y_range is not None:
            pi.setYRange(*y_range, padding=0)
        else:
            pi.enableAutoRange("y", True)
        self.curve = self.plot.plot(pen=pg.mkPen(theme.SERIES[field], width=1.5), connect="finite")
        self.curve.setClipToView(True)
        self.curve.setDownsampling(auto=True, method="peak")
        lay.addWidget(self.plot, 1)

    def redraw(self) -> None:
        t = self._store.t
        t_max = float(t[-1]) if len(t) else self.window_sec
        lo = t_max - self.window_sec
        i = max(0, int(np.searchsorted(t, lo)) - 1)  # one point before the window, so the line enters it
        y = self._store.series(self._field)
        # Copies: pyqtgraph keeps what it is given, and the store shifts its buffer in place when it trims.
        self.curve.setData(t[i:].copy(), y[i:].copy())
        self.plot.setXRange(lo, t_max, padding=0)
