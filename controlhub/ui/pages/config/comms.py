"""Config -> Communications (pages/config/CommsConfigPage.tsx): the link source, serial
port and baud rate, MQTT broker and topics. Saved to settings.json."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (QButtonGroup, QComboBox, QGridLayout, QHBoxLayout, QRadioButton, QToolButton,
                               QVBoxLayout, QWidget)

from ....asyncutil import spawn
from ....context import Context
from ....settings import settings
from ....types import CommsConfig, MqttConfig, SerialConfig
from ...widgets.chrome import Alert, Field, Panel, button, label

BAUD_RATES = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600, 1000000, 2000000]
KINDS = [("sim", "Simulator"), ("serial", "Serial port"), ("mqtt", "MQTT")]


class CommsConfigPage(QWidget):
    def __init__(self, ctx: Context) -> None:
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        link = Panel("Link")
        link.body.addWidget(label("Source", "caption"))
        radios = QHBoxLayout()
        self.kind = QButtonGroup(self)
        for i, (_k, text) in enumerate(KINDS):
            rb = QRadioButton(text)
            self.kind.addButton(rb, i)
            radios.addWidget(rb)
        radios.addStretch()
        link.body.addLayout(radios)
        self.kind.idClicked.connect(lambda _i: self._show_kind())
        lay.addWidget(link)

        # ---- serial
        self.serial = Panel("Serial port")
        g = QGridLayout()
        g.setHorizontalSpacing(16)
        port_box = QVBoxLayout()
        port_box.setSpacing(3)
        port_box.addWidget(label("Port", "caption"))
        port_row = QHBoxLayout()
        self.port = QComboBox()
        port_row.addWidget(self.port, 1)
        rescan = QToolButton()
        rescan.setText("⟳")
        rescan.setToolTip("Rescan ports")
        rescan.setStyleSheet("QToolButton { font-size: 16px; }")
        rescan.clicked.connect(self._refresh_ports)
        port_row.addWidget(rescan)
        port_box.addLayout(port_row)
        self.no_ports = label("No ports found", "helper")
        port_box.addWidget(self.no_ports)
        baud_box = QVBoxLayout()
        baud_box.setSpacing(3)
        baud_box.addWidget(label("Baud rate", "caption"))
        self.baud = QComboBox()
        for b in BAUD_RATES:
            self.baud.addItem(str(b), b)
        baud_box.addWidget(self.baud)
        baud_box.addStretch()
        g.addLayout(port_box, 0, 0)
        g.addLayout(baud_box, 0, 1)
        g.setColumnStretch(0, 2)
        g.setColumnStretch(1, 1)
        self.serial.body.addLayout(g)
        lay.addWidget(self.serial)

        # ---- MQTT
        self.mqtt = Panel("MQTT broker")
        g = QGridLayout()
        g.setHorizontalSpacing(16)
        g.setVerticalSpacing(12)
        self.url = Field("Broker URL", "mqtt://host:1883, mqtts://host:8883 or ws://host:9001")
        self.up = Field("Telemetry topic", "SerLink up: hub → app")
        self.down = Field("Command topic", "SerLink down: app → hub")
        self.user = Field("Username")
        self.password = Field("Password", password=True)
        g.addWidget(self.url, 0, 0, 1, 2)
        g.addWidget(self.up, 1, 0)
        g.addWidget(self.down, 1, 1)
        g.addWidget(self.user, 2, 0)
        g.addWidget(self.password, 2, 1)
        self.mqtt.body.addLayout(g)
        lay.addWidget(self.mqtt)

        buttons = QHBoxLayout()
        buttons.addWidget(button("Save && connect", lambda: self._save(True)))
        buttons.addWidget(button("Save", lambda: self._save(False), "outlined"))
        buttons.addStretch()
        lay.addLayout(buttons)
        self.msg = Alert()
        lay.addWidget(self.msg)

        self._ports: list[str] = []
        self._load()

    def showEvent(self, e) -> None:  # noqa: N802
        # Read afresh each time the page is shown, as the React page did on mount.
        super().showEvent(e)
        self._load()

    def _load(self) -> None:
        cfg = settings.get().comms
        self.kind.button([k for k, _ in KINDS].index(cfg.kind)).setChecked(True)
        self._path = cfg.serial.path
        self._refresh_ports()
        i = self.baud.findData(cfg.serial.baud_rate)
        if i < 0:
            self.baud.addItem(str(cfg.serial.baud_rate), cfg.serial.baud_rate)
            i = self.baud.count() - 1
        self.baud.setCurrentIndex(i)
        m = cfg.mqtt
        self.url.set_text(m.url)
        self.up.set_text(m.telemetry_topic)
        self.down.set_text(m.command_topic)
        self.user.set_text(m.username)
        self.password.set_text(m.password)
        self._show_kind()

    def _refresh_ports(self) -> None:
        current = self.port.currentData() if self.port.count() else self._path
        self.port.clear()
        try:
            ports = self.ctx.comms.list_ports()
        except Exception as e:  # noqa: BLE001
            self.msg.show_message(str(e))
            ports = []
        for p in ports:
            self.port.addItem(f"{p.path} — {p.manufacturer}" if p.manufacturer else p.path, p.path)
        self.no_ports.setVisible(not ports)
        # A saved port that isn't plugged in shows as no selection, as in the Electron app.
        self.port.setCurrentIndex(self.port.findData(current or self._path))

    def _show_kind(self) -> None:
        kind = KINDS[self.kind.checkedId()][0]
        self.serial.setVisible(kind == "serial")
        self.mqtt.setVisible(kind == "mqtt")

    def _config(self) -> CommsConfig:
        cur = settings.get().comms
        return CommsConfig(
            kind=KINDS[self.kind.checkedId()][0],
            serial=replace(cur.serial, path=self.port.currentData() or "", baud_rate=self.baud.currentData())
            if self.port.currentIndex() >= 0 else SerialConfig(path=cur.serial.path, baud_rate=self.baud.currentData()),
            mqtt=MqttConfig(url=self.url.text().strip(), telemetry_topic=self.up.text().strip(),
                            command_topic=self.down.text().strip(), username=self.user.text(),
                            password=self.password.text()))

    def _save(self, and_connect: bool) -> None:
        try:
            cfg = settings.update(comms=self._config()).comms
        except OSError as e:
            self.msg.show_message(str(e))
            return
        self._path = cfg.serial.path
        if and_connect:
            spawn(self.ctx.comms.connect(cfg))
        self.msg.show_message("Saved; connecting…" if and_connect else "Saved", "success")
