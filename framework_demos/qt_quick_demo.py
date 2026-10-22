"""Candidate 2: PySide6 + Qt Quick (QML), the Material style (dark), gauges as QML
Shapes, and strip charts in QtCharts (QtGraphs, its successor, crashes on load with
PySide6 6.12 / Python 3.14). The UI is qt_quick_demo.qml; this file is the Python
side: a Backend QObject that exposes the sim to QML, and feeds the charts.

Run:  .venv\\Scripts\\python qt_quick_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import Property, QObject, QPointF, Qt, QTimer, Signal, Slot
from PySide6.QtCharts import QLineSeries
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication  # QtCharts' ChartView needs a QApplication

from common.sim import CURRENT_MAX, DIAL_RPM_MAX, RPM_MAX, SCENARIOS, WINDOW_SEC, FpsMeter, HubSim


class Backend(QObject):
    """The sim, as QML properties. frame fires at ~60 Hz (gauges), ui at ~10 Hz (controls)."""

    frame = Signal()
    ui = Signal()

    def __init__(self):
        super().__init__()
        self.sim = HubSim()
        self.fps = FpsMeter()
        self.series: dict[str, QLineSeries] = {}
        self.y_axes: dict[str, QObject] = {}
        self.x_axes: list[QObject] = []
        self._n = 0
        self.timer = QTimer(self, interval=16, timeout=self._tick)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)

    # ---- constants
    rpmMax = Property(float, lambda s: RPM_MAX, constant=True)
    currentMax = Property(float, lambda s: CURRENT_MAX, constant=True)
    dialMax = Property(int, lambda s: DIAL_RPM_MAX, constant=True)
    scenarios = Property(list, lambda s: SCENARIOS, constant=True)

    # ---- 60 Hz
    rpm = Property(float, lambda s: s.sim.latest("rpm") or 0.0, notify=frame)
    duty = Property(float, lambda s: s.sim.latest("duty") or 0.0, notify=frame)
    current = Property(float, lambda s: s.sim.latest("current") or 0.0, notify=frame)

    # ---- 10 Hz
    dialValue = Property(int, lambda s: s.sim.dial().value or 0, notify=ui)
    dialState = Property(str, lambda s: s.sim.dial().state, notify=ui)
    dialTip = Property(str, lambda s: s.sim.dial().tooltip, notify=ui)
    chipText = Property(str, lambda s: s.sim.mode_chip()[0], notify=ui)
    chipRole = Property(str, lambda s: s.sim.mode_chip()[1], notify=ui)
    direction = Property(str, lambda s: s.sim.direction, notify=ui)
    startBlocked = Property(str, lambda s: s.sim.start_blocked(), notify=ui)
    liftBlocked = Property(str, lambda s: s.sim.lift_blocked(), notify=ui)
    busy = Property(str, lambda s: s.sim.busy or "", notify=ui)
    done = Property(bool, lambda s: s.sim.done, notify=ui)
    liftCaption = Property(str, lambda s: s.sim.lift_caption(), notify=ui)
    liftProgress = Property(str, lambda s: s.sim.lift_progress(), notify=ui)
    fpsText = Property(str, lambda s: s.fps.text(), notify=ui)
    scenarioIndex = Property(int, lambda s: SCENARIOS.index(s.sim.scenario), notify=ui)

    # ---- commands
    @Slot()
    def start(self): self.sim.start()

    @Slot()
    def stop(self): self.sim.stop()

    @Slot(str)
    def setDirection(self, d): self.sim.set_direction(d)

    @Slot()
    def liftUp(self): self.sim.lift_up()

    @Slot()
    def liftDown(self): self.sim.lift_down()

    @Slot()
    def liftMove(self): self.sim.lift_move()

    @Slot(str)
    def setMoveMode(self, m):
        self.sim.move_mode = m
        self.ui.emit()

    @Slot(str)
    def setLiftDirection(self, d): self.sim.lift_direction = d

    @Slot(int)
    def setRpm(self, v):
        self.sim.set_rpm(v)
        self.ui.emit()

    @Slot()
    def remoteButton(self): self.sim.remote_button()

    @Slot(int)
    def setScenario(self, i): self.sim.set_scenario(SCENARIOS[i])

    @Slot()
    def frameSwapped(self): self.fps.frame()

    # ---- the loop
    @Slot(str, QLineSeries, QObject, QObject)
    def registerChart(self, field, series, x_axis, y_axis):
        """Each StripChart calls this when it's built (findChild can't see into a ChartView)."""
        self.series[field] = series
        self.x_axes.append(x_axis)
        self.y_axes[field] = y_axis

    def bind_charts(self, _root: QObject):
        self.timer.start()

    def _tick(self):
        self.sim.step()
        self.frame.emit()
        t_max = max(WINDOW_SEC, self.sim.now())
        for x in self.x_axes:
            x.setProperty("min", t_max - WINDOW_SEC)
            x.setProperty("max", t_max)
        for k, s in self.series.items():
            t, y = self.sim.history(k)
            i = int(np.searchsorted(t, t_max - WINDOW_SEC - 0.1))
            t, y = t[i:], y[i:]
            s.replace([QPointF(a, b) for a, b in zip(t.tolist(), y.tolist())])
            if k != "duty" and len(y):  # duty is fixed 0..100, the others auto-scale
                lo, hi = float(y.min()), float(y.max())
                pad = max((hi - lo) * 0.1, 0.05 if k == "current" else 5)
                ax = self.y_axes[k]
                ax.setRange(max(0.0, lo - pad), hi + pad)
                ax.applyNiceNumbers()
        self._n += 1
        if self._n % 6 == 0:
            self.ui.emit()


def main():
    QQuickStyle.setStyle("Material")
    app = QApplication(sys.argv)
    backend = Backend()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("hub", backend)
    # Tear the QML down while `hub` still exists (else every binding logs "of null" at exit)
    app.aboutToQuit.connect(lambda: engine.rootObjects()[0].deleteLater())
    engine.load(Path(__file__).with_name("qt_quick_demo.qml"))
    if not engine.rootObjects():
        sys.exit(1)
    root = engine.rootObjects()[0]
    root.frameSwapped.connect(backend.frameSwapped)
    backend.bind_charts(root)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
