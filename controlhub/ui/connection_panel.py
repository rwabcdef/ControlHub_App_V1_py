"""Left column: connection summary, connect / disconnect, and the LIFT0 ping
(layouts/ConnectionPanel.tsx)."""
from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..asyncutil import spawn
from ..context import Context
from ..settings import settings
from . import theme
from .widgets.chrome import Alert, CmdButton, Lamp, divider, label

# result: (label, tone, hint)
PING_RESULT = {
    "ok": ("OK", theme.SUCCESS, "PINGBACK: the hub has a LIFT0 socket"),
    "noSocket": ("No socket", theme.WARNING, "Link up, but the hub has no LIFT0 socket"),
    "timeout": ("No answer", theme.ERROR, "Link down, hub not running, or its firmware predates PING"),
    "unexpected": ("Unexpected reply", theme.WARNING, "Answered with neither PINGBACK nor ACK_OK"),
    "error": ("Error", theme.ERROR, "The ping could not be sent"),
    "closed": ("Link closed", theme.ERROR, "Disconnected before the answer"),
}


class ConnectionPanel(QWidget):
    def __init__(self, ctx: Context, open_settings: Callable[[], None]) -> None:
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)
        lay.addWidget(label("CONNECTION", "overline"))
        summary = QVBoxLayout()
        summary.setSpacing(1)
        self.kind = label("…")
        self.kind.setStyleSheet("font-weight: 600;")
        self.target = label("", "caption", wrap=True)
        summary.addWidget(self.kind)
        summary.addWidget(self.target)
        lay.addLayout(summary)
        self.error = Alert(closable=False)
        lay.addWidget(self.error)
        self.connect_btn = CmdButton("Connect")
        self.connect_btn.clicked.connect(lambda: spawn(ctx.comms.connect()))
        self.disconnect_btn = CmdButton("Disconnect", variant="outlined", tone="warning")
        self.disconnect_btn.clicked.connect(lambda: spawn(ctx.comms.disconnect()))
        lay.addWidget(self.connect_btn)
        lay.addWidget(self.disconnect_btn)

        # LIFT0 is only on the hub's MQTT link
        self.ping_box = QWidget()
        pl = QVBoxLayout(self.ping_box)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(8)
        self.ping_btn = CmdButton("Ping lift", variant="outlined")
        self.ping_btn.clicked.connect(lambda: spawn(ctx.lift.send_ping()))
        self.ping_lamp = Lamp("Idle")
        pl.addWidget(self.ping_btn)
        pl.addWidget(self.ping_lamp)
        lay.addWidget(self.ping_box)

        lay.addWidget(divider())
        self.settings_btn = CmdButton("Connection settings…", variant="text")
        self.settings_btn.clicked.connect(open_settings)
        lay.addWidget(self.settings_btn)
        lay.addStretch()

        ctx.comms.state_changed.connect(lambda _s: self.refresh())
        ctx.lift.changed.connect(self.refresh_ping)
        self.refresh()

    def refresh(self) -> None:
        state = self.ctx.comms.state
        # The summary is re-read on every state change (the config may have been saved).
        cfg = settings.get().comms
        self.kind.setText(cfg.kind.upper())
        self.target.setText(f"{cfg.serial.path or '(no port)'} @ {cfg.serial.baud_rate}" if cfg.kind == "serial"
                            else cfg.mqtt.url if cfg.kind == "mqtt" else "Built-in motor simulator")
        if state.error:
            self.error.show_message(state.error)
        else:
            self.error.hide()
        live = state.status in ("connected", "error")
        self.connect_btn.setVisible(not live)
        self.disconnect_btn.setVisible(live)
        self.connect_btn.set_state(loading=state.status == "connecting")
        self.ping_box.setVisible(state.status == "connected" and state.kind == "mqtt")
        self.refresh_ping()

    def refresh_ping(self) -> None:
        lift = self.ctx.lift
        pinging = lift.ping_phase == "pinging"
        self.ping_btn.set_state(busy_elsewhere=pinging)
        if lift.ping_phase == "idle" or lift.ping is None and not pinging:
            self.ping_lamp.set("Idle", None)
            self.ping_lamp.setToolTip("")
        elif pinging:
            self.ping_lamp.set("Pinging…", None, busy=True)
            self.ping_lamp.setToolTip("")
        else:
            r = lift.ping
            text, tone, hint = PING_RESULT[r.result]  # type: ignore[union-attr]
            self.ping_lamp.set(f"OK · {r.elapsed_ms} ms" if r.result == "ok" else text, tone)  # type: ignore[union-attr]
            self.ping_lamp.setToolTip(r.error or hint)  # type: ignore[union-attr]
