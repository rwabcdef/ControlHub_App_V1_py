"""App shell (layouts/MainLayout.tsx): header, nav tabs, the left Connection panel, the
page area and the status footer. The Electron app's right-hand "Motor control" panel is
deliberately not ported (it only drove the simulator's placeholder commands)."""
from __future__ import annotations

import asyncio
import sys

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QMainWindow, QScrollArea, QStackedWidget, QTabBar, QToolButton,
                               QVBoxLayout, QWidget)

from ..asyncutil import cancel_all, spawn
from ..context import Context
from . import theme
from .connection_panel import ConnectionPanel
from .pages.config import ConfigPage
from .pages.dashboard import DashboardPage
from .pages.dev import DevPage
from .pages.direct import DirectPage
from .pages.files import FilesPage
from .pages.log import LogPage
from .widgets.chrome import Chip, label

NAV = ["Dashboard", "Direct", "Config", "MQTT log", "Files", "Dev"]
STATUS_ROLE = {"connected": "success", "connecting": "info", "error": "error", "disconnected": "default"}


def _panel_icon(kind: str) -> QIcon:
    """The header's two toggles, drawn: 'sidebar' (a window with a left column, MUI's
    ViewSidebar) and 'split' (MUI's VerticalSplit). Grey normally, primary when checked."""
    icon = QIcon()
    for mode_state, color in ((QIcon.State.Off, theme.TEXT_2), (QIcon.State.On, theme.PRIMARY)):
        pm = QPixmap(40, 40)
        pm.setDevicePixelRatio(2)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(color)
        p.setPen(QPen(c, 1.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(2, 4, 16, 12), 1.5, 1.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        if kind == "sidebar":
            p.drawRect(QRectF(2, 4, 5, 12))
        else:
            p.drawRect(QRectF(2, 4, 7, 12))
            for y in (7.5, 10, 12.5):
                p.drawRect(QRectF(11, y - 0.6, 5, 1.2))
        p.end()
        icon.addPixmap(pm, QIcon.Mode.Normal, mode_state)
    return icon


def _hline() -> QFrame:
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet(f"background: {theme.DIVIDER};")
    return f


def _vline() -> QFrame:
    f = QFrame()
    f.setFixedWidth(1)
    f.setStyleSheet(f"background: {theme.DIVIDER};")
    return f


class MainWindow(QMainWindow):
    def __init__(self, ctx: Context) -> None:
        super().__init__()
        self.ctx = ctx
        # The context's QObjects live and die with the window, so Qt deletes them in its own
        # order when the window goes, not Python's GC at some point afterwards.
        for obj in (ctx.comms, ctx.hub, ctx.ctrl, ctx.direct, ctx.lift, ctx.control_hub, ctx.display, ctx.mqtt_log, ctx.clock):
            obj.setParent(self)
        self._closing = False
        self._shut_down = False
        self.finished = asyncio.Event()
        """Set once the window has closed and everything is shut down"""
        self.setWindowTitle("ControlHub")
        self.resize(1440, 900)
        self.setMinimumSize(1024, 640)
        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # ---- header
        header = QWidget()
        h = QHBoxLayout(header)
        h.setContentsMargins(10, 6, 12, 6)
        h.setSpacing(6)
        self.left_toggle = self._tool("sidebar", "Toggle connection panel")
        self.left_toggle.clicked.connect(
            lambda: ctx.display.set(left_panel_open=not ctx.display.values.left_panel_open))
        self.control_toggle = self._tool("split", "Toggle Control panel", checkable=True)
        self.control_toggle.clicked.connect(
            lambda: ctx.display.set(dash_control_open=not ctx.display.values.dash_control_open))
        h.addWidget(self.left_toggle)
        h.addWidget(self.control_toggle)
        title = label(f"<b>ControlHub</b> <span style='color:{theme.TEXT_2}'>AA26</span>")
        title.setStyleSheet("font-size: 16px;")
        h.addWidget(title)
        h.addStretch()
        self.conn_chip = Chip()
        h.addWidget(self.conn_chip)
        v.addWidget(header)
        v.addWidget(_hline())

        # ---- nav
        nav = QWidget()
        nl = QHBoxLayout(nav)
        nl.setContentsMargins(8, 0, 8, 0)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        for name in NAV:
            self.tabs.addTab(name)
        nl.addWidget(self.tabs)
        nl.addStretch()
        v.addWidget(nav)
        v.addWidget(_hline())

        # ---- left aside + pages
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.left = QScrollArea()
        self.left.setWidgetResizable(True)
        self.left.setFixedWidth(240)
        self.left.setWidget(ConnectionPanel(ctx, lambda: self.navigate("Config", "Communications")))
        self.left_line = _vline()
        body.addWidget(self.left)
        body.addWidget(self.left_line)

        self.stack = QStackedWidget()
        self.config = ConfigPage(ctx)
        self.pages: dict[str, QWidget] = {"Dashboard": DashboardPage(ctx), "Direct": DirectPage(ctx),
                                          "Config": self.config,
                                          "MQTT log": LogPage(ctx), "Files": FilesPage(ctx), "Dev": DevPage(ctx)}
        for name in NAV:
            page = self.pages[name]
            holder = QWidget()
            hl = QVBoxLayout(holder)
            hl.setContentsMargins(12, 12, 12, 12)
            hl.addWidget(page)
            self.stack.addWidget(holder)
        body.addWidget(self.stack, 1)
        v.addLayout(body, 1)

        # ---- footer (StatusFooter.tsx): low-rate readout, polled at 2 Hz
        v.addWidget(_hline())
        footer = QWidget()
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(12, 3, 12, 3)
        fl.setSpacing(24)
        self.rate = label("", "caption")
        self.buffered = label("", "caption")
        fl.addWidget(self.rate)
        fl.addWidget(self.buffered)
        fl.addStretch()
        fl.addWidget(label(sys.platform, "caption"))
        v.addWidget(footer)
        self._footer_timer = QTimer(self, interval=500, timeout=self._refresh_footer)
        self._footer_timer.start()

        self.tabs.currentChanged.connect(self._on_tab)
        ctx.display.changed.connect(self._apply_display)
        ctx.comms.state_changed.connect(lambda _s: self._refresh_chip())
        self._apply_display()
        self._refresh_chip()
        self._refresh_footer()

    @staticmethod
    def _tool(kind: str, tip: str, checkable: bool = False) -> QToolButton:
        b = QToolButton()
        b.setIcon(_panel_icon(kind))
        b.setIconSize(QSize(20, 20))
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    def closeEvent(self, e) -> None:  # noqa: N802
        """Shut down while the event loop still runs: release the port / broker connection
        and finish every background task, then close for real and set `finished`, which
        the app's main coroutine waits on (see __main__.py)."""
        if self._shut_down:
            e.accept()
            return
        e.ignore()
        if self._closing:
            return
        self._closing = True

        async def shutdown() -> None:
            try:
                await self.ctx.comms.disconnect()
                await cancel_all()
            finally:
                self._shut_down = True
                self.close()
                self.finished.set()

        spawn(shutdown())

    def navigate(self, page: str, sub: str | None = None) -> None:
        self.tabs.setCurrentIndex(NAV.index(page))
        if page == "Config" and sub:
            self.config.show_tab(sub)

    def _on_tab(self, i: int) -> None:
        self.stack.setCurrentIndex(i)
        self.control_toggle.setVisible(NAV[i] == "Dashboard")

    def _apply_display(self) -> None:
        d = self.ctx.display.values
        self.left.setVisible(d.left_panel_open)
        self.left_line.setVisible(d.left_panel_open)
        self.control_toggle.setChecked(d.dash_control_open)

    def _refresh_chip(self) -> None:
        s = self.ctx.comms.state
        self.conn_chip.set(f"{s.kind.upper()} · {s.status}", STATUS_ROLE[s.status], outlined=True)

    def _refresh_footer(self) -> None:
        t = self.ctx.telemetry
        self.rate.setText(f"Rate: {t.rate:.0f} Hz")
        self.buffered.setText(f"Buffered: {len(t):,} samples")
