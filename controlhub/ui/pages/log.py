"""MQTT log (pages/LogPage.tsx): every line of MQTT traffic between this app and the hub,
both ways - frames, acks and status. Collected from app start (state/mqtt_log.py), so
this page also shows what came before it was opened. Pause freezes the view; lines are
still collected meanwhile."""
from __future__ import annotations

import html
from datetime import datetime, timezone

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLineEdit, QTextBrowser, QVBoxLayout, QWidget

from ...context import Context
from ...types import MqttLogLine
from .. import theme
from ..widgets.chrome import Panel, button

SHOWN = 500
"""Lines rendered at once - the newest. The store keeps more."""


def _time(t_ms: float) -> str:
    return datetime.fromtimestamp(t_ms / 1000, timezone.utc).strftime("%H:%M:%S.%f")[:-3]


class LogPage(QWidget):
    def __init__(self, ctx: Context) -> None:
        super().__init__()
        self.store = ctx.mqtt_log
        actions = QWidget()
        row = QHBoxLayout(actions)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter, e.g. CTRL0")
        self.filter.setFixedWidth(200)
        self.filter.textChanged.connect(lambda _t: self.render())
        self.pause = QCheckBox("Pause")
        self.pause.toggled.connect(self.store.set_paused)
        self.follow = QCheckBox("Follow")
        self.follow.setChecked(True)
        self.follow.toggled.connect(lambda _c: self.render())
        row.addWidget(self.filter)
        row.addWidget(self.pause)
        row.addWidget(self.follow)
        row.addWidget(button("⌫  Clear", self.store.clear, "text"))

        self.panel = Panel("MQTT traffic (0 lines)", actions)
        self.view = QTextBrowser()
        self.view.setObjectName("mono")
        self.view.setOpenLinks(False)
        self.view.setStyleSheet(f"QTextBrowser {{ border: none; font-family: {theme.MONO}; font-size: 13px; }}")
        self.panel.body.addWidget(self.view)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.panel)
        self.store.changed.connect(self.render)
        self.render()

    def hideEvent(self, e) -> None:  # noqa: N802
        # Leaving the page un-pauses, as the React page's cleanup did.
        self.pause.setChecked(False)
        super().hideEvent(e)

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self.render()

    def render(self) -> None:
        lines = self.store.snapshot
        self.panel.set_title(f"MQTT traffic ({len(lines)} lines)")
        if not self.isVisible():
            return
        f = self.filter.text().strip().upper()
        matching = [ln for ln in lines if f in ln.line.upper()] if f else lines
        shown = matching[-SHOWN:]
        if not shown:
            self.view.setHtml(f"<span style='color:{theme.TEXT_2}; font-family: Segoe UI'>"
                              "Nothing yet - MQTT traffic shows here once connected over MQTT.</span>")
            return
        bar = self.view.verticalScrollBar()
        keep = bar.value()
        self.view.setHtml("<pre style='margin:0'>" + "\n".join(self._row(ln) for ln in shown) + "</pre>")
        if self.follow.isChecked():
            bar.setValue(bar.maximum())
        else:
            bar.setValue(keep)

    @staticmethod
    def _row(ln: MqttLogLine) -> str:
        out = ln.dir == "out"
        color = theme.SUCCESS if out else theme.INFO
        return (f"<span style='color:{theme.TEXT_2}'>{_time(ln.t)}</span>  "
                f"<span style='color:{color}'>{'out' if out else 'in '}</span>   {html.escape(ln.line)}")
