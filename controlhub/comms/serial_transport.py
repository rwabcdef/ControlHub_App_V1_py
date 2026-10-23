"""Serial transport: SerLink over newline-terminated lines, as the hub's uart2 (serial.ts).

USART2 on PD5/PD6 via the FTDI cable, 115200 baud (see the hub README) - not the
ST-LINK virtual COM port. Non-SerLink lines are parsed as plain JSON / CSV telemetry.
The hub has no LIFT0 socket on this link, so there are no lift calls here.

QSerialPort is event-driven (readyRead on the Qt event loop, which qasync shares
with asyncio), so no extra thread is involved.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo

from ..types import (CtrlDirection, CtrlReadback, CtrlSettings, HubClockReading, HubClockSetResult, HubSocket,
                     MotorDirection, MotorId, MotorReadback, SerialConfig, SerialPortInfo)
from .errors import CommsError
from .hub_link import HubLink
from .transport import TransportEvents


def list_serial_ports() -> list[SerialPortInfo]:
    out = []
    for p in QSerialPortInfo.availablePorts():
        out.append(SerialPortInfo(
            path=p.portName(), manufacturer=p.manufacturer(), serial_number=p.serialNumber(),
            vendor_id=f"{p.vendorIdentifier():04x}" if p.hasVendorIdentifier() else "",
            product_id=f"{p.productIdentifier():04x}" if p.hasProductIdentifier() else ""))
    return out


class SerialTransport:
    def __init__(self, cfg: SerialConfig, ev: TransportEvents) -> None:
        self._cfg = cfg
        self._ev = ev
        self._port: QSerialPort | None = None
        self._link: HubLink | None = None
        self._buf = bytearray()

    async def open(self) -> None:
        if not self._cfg.path:
            raise CommsError("No serial port selected")
        port = QSerialPort()
        port.setPortName(self._cfg.path)
        port.setBaudRate(self._cfg.baud_rate)
        self._link = HubLink(self._write_line, self._ev)
        if not port.open(QSerialPort.OpenModeFlag.ReadWrite):
            err = port.errorString()
            self._link.close()
            self._link = None
            raise CommsError(f"Could not open {self._cfg.path}: {err}")
        self._port = port
        port.readyRead.connect(self._on_ready_read)
        port.errorOccurred.connect(self._on_error)

    async def close(self) -> None:
        if self._link is not None:
            self._link.close()
            self._link = None
        port, self._port = self._port, None
        if port is not None:
            port.errorOccurred.disconnect(self._on_error)
            port.readyRead.disconnect(self._on_ready_read)
            if port.isOpen():
                port.close()
            port.deleteLater()

    def _on_ready_read(self) -> None:
        port, link = self._port, self._link
        if port is None or link is None:
            return
        self._buf += bytes(port.readAll().data())
        while (i := self._buf.find(b"\n")) >= 0:
            line = self._buf[:i].decode("utf-8", errors="replace")
            del self._buf[: i + 1]
            link.receive_line(line)

    def _on_error(self, error: QSerialPort.SerialPortError) -> None:
        if error == QSerialPort.SerialPortError.NoError or self._port is None:
            return
        self._ev.error(CommsError(f"{self._cfg.path}: {self._port.errorString()}"))
        if error == QSerialPort.SerialPortError.ResourceError:  # unplugged
            self._ev.close()

    async def _write_line(self, line: str) -> None:
        port = self._port
        if port is None or not port.isOpen():
            raise CommsError("Serial port not open")
        if port.write((line + "\n").encode("utf-8")) < 0:
            raise CommsError(f"{self._cfg.path}: {port.errorString()}")

    def _live(self) -> HubLink:
        if self._link is None or self._port is None or not self._port.isOpen():
            raise CommsError("Serial port not open")
        return self._link

    async def send(self, text: str) -> str | None:
        return await self._live().send(text)

    async def socket_send(self, protocol: HubSocket, data: str, ack: bool) -> str | None:
        return await self._live().socket_send(protocol, data, ack)

    async def ctrl_get(self) -> CtrlReadback:
        return await self._live().ctrl_get()

    async def ctrl_set(self, s: CtrlSettings) -> CtrlSettings:
        return await self._live().ctrl_set(s)

    async def ctrl_start(self) -> None:
        await self._live().ctrl_start()

    async def ctrl_stop(self) -> None:
        await self._live().ctrl_stop()

    async def ctrl_set_direction(self, direction: CtrlDirection) -> None:
        await self._live().ctrl_set_direction(direction)

    async def motor_get(self, motor: MotorId) -> MotorReadback:
        return await self._live().motor_get(motor)

    async def motor_set_duty(self, motor: MotorId, duty: int) -> int:
        return await self._live().motor_set_duty(motor, duty)

    async def motor_set_direction(self, motor: MotorId, direction: MotorDirection) -> MotorDirection:
        return await self._live().motor_set_direction(motor, direction)

    async def rtc_set(self, when: datetime) -> HubClockSetResult:
        return await self._live().rtc_set(when)

    async def rtc_get(self) -> HubClockReading:
        return await self._live().rtc_get()
