"""Everything the UI talks to, built once at start-up and handed to each page."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from .comms.hub import CommsHub
from .state.mqtt_log import MqttLogStore
from .state.stores import ControlHubStore, CtrlStore, DirectStore, DisplayStore, HubStore, LiftStore
from .state.telemetry import TelemetryStore, telemetry

FRAME_MS = 16


class FrameClock(QObject):
    """One display-rate timer for every live widget (useTelemetryFrame): `frame` fires at
    ~60 Hz, but only when new samples have arrived since the last one."""

    frame = Signal()

    def __init__(self, store: TelemetryStore) -> None:
        super().__init__()
        self._store = store
        self._drawn = -1
        self._timer = QTimer(self, interval=FRAME_MS, timeout=self._tick)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.start()

    def _tick(self) -> None:
        if self._store.version != self._drawn:
            self._drawn = self._store.version
            self.frame.emit()


@dataclass
class Context:
    comms: CommsHub
    telemetry: TelemetryStore
    hub: HubStore
    ctrl: CtrlStore
    direct: DirectStore
    lift: LiftStore
    control_hub: ControlHubStore
    display: DisplayStore
    mqtt_log: MqttLogStore
    clock: FrameClock


def build_context() -> Context:
    comms = CommsHub(telemetry)
    hub = HubStore(comms)
    mqtt_log = MqttLogStore()
    comms.mqtt_log.connect(mqtt_log.push)
    # A new connection starts with an empty telemetry buffer.
    comms.state_changed.connect(lambda s: s.status == "connecting" and telemetry.clear())
    return Context(comms=comms, telemetry=telemetry, hub=hub, ctrl=CtrlStore(comms, hub),
                   direct=DirectStore(comms, hub), lift=LiftStore(comms),
                   control_hub=ControlHubStore(), display=DisplayStore(), mqtt_log=mqtt_log,
                   clock=FrameClock(telemetry))
