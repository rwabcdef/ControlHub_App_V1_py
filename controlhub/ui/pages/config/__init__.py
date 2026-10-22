"""Config: Communications, ControlHub and Display sub-pages (pages/config/ConfigLayout.tsx)."""
from __future__ import annotations

from PySide6.QtWidgets import QScrollArea, QStackedWidget, QTabBar, QVBoxLayout, QWidget

from ....context import Context
from .comms import CommsConfigPage
from .control_hub import ControlHubConfigPage
from .display import DisplayConfigPage

TABS = ["Communications", "ControlHub", "Display"]


class ConfigPage(QWidget):
    def __init__(self, ctx: Context) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        for t in TABS:
            self.tabs.addTab(t)
        outer.addWidget(self.tabs)
        self.stack = QStackedWidget()
        for page in (CommsConfigPage(ctx), ControlHubConfigPage(ctx), DisplayConfigPage(ctx)):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            holder = QWidget()
            hl = QVBoxLayout(holder)
            hl.setContentsMargins(0, 12, 0, 0)
            page.setMaximumWidth(900)
            hl.addWidget(page)
            hl.addStretch()
            scroll.setWidget(holder)
            self.stack.addWidget(scroll)
        outer.addWidget(self.stack, 1)
        self.tabs.currentChanged.connect(self.stack.setCurrentIndex)

    def show_tab(self, name: str) -> None:
        self.tabs.setCurrentIndex(TABS.index(name))
