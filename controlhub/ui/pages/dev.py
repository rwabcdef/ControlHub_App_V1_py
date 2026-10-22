"""Dev tools (pages/DevPage.tsx): raw data to the hub's SerLink sockets."""
from __future__ import annotations

import html
import itertools
import time
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QVBoxLayout, QWidget

from ...asyncutil import spawn
from ...context import Context
from ...types import HubSocket
from .. import theme
from ..widgets.chrome import CmdButton, Panel, button, label

HISTORY = 20
"""Sends kept in each socket's history"""
_ids = itertools.count(1)


@dataclass
class Sent:
    id: int
    time: str
    frame: str  # 'T' | 'U'
    payload: str
    ok: bool | None = None
    """None while waiting for the ack"""
    reply: str | None = None


class SocketSender(Panel):
    """Payload box + Send for one socket, with the recent sends and their outcomes."""

    def __init__(self, ctx: Context, protocol: HubSocket, placeholder: str, default_ack: bool,
                 mqtt_only: bool = False) -> None:
        self.clear_btn = button("Clear", lambda: self._set_history([]), "text")
        super().__init__(protocol.lower(), self.clear_btn)
        self.ctx, self.protocol, self.mqtt_only = ctx, protocol, mqtt_only
        self.history: list[Sent] = []
        b = self.body
        row = QHBoxLayout()
        row.setSpacing(8)
        box = QVBoxLayout()
        box.setSpacing(3)
        box.addWidget(label(f"{protocol} payload", "caption"))
        self.payload = QLineEdit()
        self.payload.setPlaceholderText(f"e.g. {placeholder}")
        self.payload.setStyleSheet(f"font-family: {theme.MONO};")
        self.payload.textChanged.connect(lambda _t: self.refresh())
        self.payload.returnPressed.connect(self._send)
        box.addWidget(self.payload)
        row.addLayout(box, 1)
        self.send_btn = CmdButton("Send  ➤")
        self.send_btn.setFixedWidth(100)
        self.send_btn.clicked.connect(self._send)
        row.addWidget(self.send_btn, 0)
        b.addLayout(row)
        self.ack = QCheckBox("Ack ('T' frame)")
        self.ack.setChecked(default_ack)
        self.ack.setToolTip("On: 'T' frame, waits for the hub's ack (and shows any data on it). Off: 'U' frame, no ack.")
        b.addWidget(self.ack)
        self.list = QLabel()
        self.list.setStyleSheet(f"QLabel {{ font-family: {theme.MONO}; font-size: 13px; border: 1px solid {theme.DIVIDER};"
                                f" border-radius: 4px; padding: 8px; }}")
        b.addWidget(self.list)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)  # content height, as on the web
        ctx.comms.state_changed.connect(lambda _s: self.refresh())
        self._set_history([])

    def _blocked(self) -> str:
        """Why Send is disabled, if it is"""
        s = self.ctx.comms.state
        if s.status != "connected":
            return "Connect first"
        if s.kind == "sim":
            return "Needs a serial or MQTT connection"
        if self.mqtt_only and s.kind != "mqtt":
            return f"{self.protocol} is only available over MQTT"
        if not self.payload.text().strip():
            return "Enter a payload"
        return ""

    def refresh(self) -> None:
        self.send_btn.set_state(self._blocked())

    def _send(self) -> None:
        if self._blocked():
            return
        text = self.payload.text().strip()
        ack = self.ack.isChecked()
        sent = Sent(next(_ids), time.strftime("%X"), "T" if ack else "U", text)
        self._set_history([sent, *self.history][:HISTORY])

        def finish(ok: bool, reply: str | None) -> None:
            sent.ok, sent.reply = ok, reply
            self._render()

        spawn(self.ctx.comms.socket_send(self.protocol, text, ack),
              on_error=lambda e: finish(False, str(e)), on_done=lambda r: finish(True, r))

    def _set_history(self, h: list[Sent]) -> None:
        self.history = h
        self._render()

    def _render(self) -> None:
        self.clear_btn.setVisible(bool(self.history))
        self.list.setVisible(bool(self.history))
        rows = []
        for s in self.history:
            if s.ok is None:
                status, color = "…", theme.TEXT_2
            elif s.ok:
                status, color = "✓" + (f" {s.reply}" if s.reply else ""), theme.SUCCESS
            else:
                status, color = f"✗ {s.reply}", theme.ERROR_TEXT
            rows.append(f"<span style='color:{theme.TEXT_2}'>{s.time}</span>&nbsp; {s.frame} {html.escape(s.payload)}"
                        f"&nbsp; <span style='color:{color}'>{html.escape(status)}</span>")
        self.list.setText("<br>".join(rows))


class DevPage(QWidget):
    def __init__(self, ctx: Context) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        lift = SocketSender(ctx, "LIFT0", "BSF234", default_ack=False, mqtt_only=True)
        ctrl = SocketSender(ctx, "CTRL0", "BGA", default_ack=True)
        for p in (lift, ctrl):
            row.addWidget(p, 1, Qt.AlignmentFlag.AlignTop)
