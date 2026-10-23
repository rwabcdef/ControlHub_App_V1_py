"""HubLink against a fake hub: the CTRL0 reads and read-back checks, status frames, LIFT0."""
import asyncio
from datetime import datetime

import pytest
from conftest import Events, FakeHub, Recorder, run

from controlhub.comms.errors import CommsError
from controlhub.comms.hub_link import HubLink
from controlhub.types import CtrlSettings


async def make(lift=True):
    w, hub, ev = Recorder(), FakeHub(), Events()
    link = HubLink(w, ev.ev, lift=lift)
    w.target, w.respond = link, hub
    return link, hub, ev, w


def test_ctrl_get():
    async def main():
        link, hub, ev, w = await make()
        hub.direction, hub.mode, hub.source = "R", "C", "R"
        r = await link.ctrl_get()
        assert (r.gain_i, r.rpm, r.measured_rpm, r.max_duty) == (0.002, 150, 148, 50)
        assert (r.hub.mode, r.hub.direction, r.hub.source) == ("control", "reverse", "remote")
        assert ev.hubs[-1] == r.hub
        assert [f.data for f in hub.received] == ["BGA", "BGM", "BGD", "BGO"]
    run(main())


def test_ctrl_set_and_read_back():
    async def main():
        link, hub, ev, w = await make()
        out = await link.ctrl_set(CtrlSettings(gain_i=0.0035, rpm=120, max_duty=60))
        assert (out.gain_i, out.rpm, out.max_duty) == (0.0035, 120, 60)
        assert [f.data for f in hub.received] == ["BI003500", "BGI", "BR0120", "BGR", "BM060", "BGM"]
        hub.mode = "L"  # the hub refuses BR during a lift move
        with pytest.raises(CommsError, match="kept 120 RPM, not 200"):
            await link.ctrl_set(CtrlSettings(rpm=200))
    run(main())


def test_ctrl_set_validation():
    async def main():
        link, *_ = await make()
        for bad, msg in ((CtrlSettings(gain_i=1.5), "Gain must be"), (CtrlSettings(gain_i=0.0000001), "Gain must be"),
                         (CtrlSettings(rpm=10000), "RPM must be"), (CtrlSettings(rpm=1.5), "RPM must be"),
                         (CtrlSettings(max_duty=19), "Max duty must be")):
            with pytest.raises(CommsError, match=msg):
                await link.ctrl_set(bad)
    run(main())


def test_status_frames_and_source_read():
    async def main():
        link, hub, ev, w = await make()
        hub.mode, hub.source = "C", "R"
        link.receive_line("CTRL0U001020CF030.0350.1234.0150")
        assert ev.samples[-1].rpm == 350 and ev.hubs[-1].mode == "control" and ev.hubs[-1].source is None
        await asyncio.sleep(0.02)  # BGO goes out on the mode change
        assert hub.received[-1].data == "BGO"
        assert ev.hubs[-1].source == "remote" and ev.hubs[-1].run_rpm == 150
        n = len(hub.received)
        link.receive_line("CTRL0U002020CF031.0360.1200.0160")
        await asyncio.sleep(0.02)
        assert len(hub.received) == n  # same mode: no new BGO, source kept
        assert ev.hubs[-1].source == "remote" and ev.hubs[-1].run_rpm == 160
        link.receive_line("CTRL0U003020IF000.0000.0000.0160")
        assert ev.hubs[-1].mode == "idle" and ev.hubs[-1].source == "none"
        link.receive_line("1500,42.5,1.23")  # plain telemetry still accepted
        assert ev.samples[-1].rpm == 1500
    run(main())


def test_commands_and_lift_frames():
    async def main():
        link, hub, ev, w = await make()
        await link.ctrl_start()
        await link.ctrl_set_direction("reverse")
        await link.ctrl_stop()
        await link.lift_start(234, "forward")
        await link.lift_start(5, "reverse")
        await link.lift_down(120)
        await link.lift_stop()
        assert [str(f)[5:6] + f.data for f in hub.received] == [
            "TBS", "TBDR", "TBX", "UBSF234", "UBSR5", "UBG120", "UBX"]
        link.receive_line("LIFT0U001015BI000234.000234")
        assert ev.lifts[-1].travelled == 234 and not ev.lifts[-1].moving
        assert (await link.lift_ping()).result == "ok"
        assert await link.socket_send("CTRL0", " BGA ", True) == "002000.0150.0148"
        with pytest.raises(CommsError, match="Lift distance must be"):
            await link.lift_start(0, "forward")
        with pytest.raises(CommsError, match="Empty payload"):
            await link.socket_send("LIFT0", "  ", False)
    run(main())


def test_send_raw_frame_or_ctrl_data():
    async def main():
        link, hub, ev, w = await make()
        assert await link.send("BGR") == "0150"
        assert w.lines[-1].startswith("CTRL0T") and w.lines[-1].endswith("BGR")
        assert await link.send("CTRL0T516003BGM") == "050"
        assert w.lines[-1] == "CTRL0T516003BGM"
    run(main())


def test_serial_link_has_no_lift_and_no_ack_message():
    async def main():
        link, hub, ev, w = await make(lift=False)
        with pytest.raises(CommsError, match="LIFT0 is only available over MQTT"):
            await link.lift_start(10, "forward")
        with pytest.raises(CommsError, match="LIFT0 is only available over MQTT"):
            await link.socket_send("LIFT0", "BX", False)
        w.respond = None
        with pytest.raises(CommsError, match="CTRL0: no ack from the hub"):
            await link.ctrl_start()
        link.close()
        with pytest.raises(CommsError, match="Link closed"):
            await link.ctrl_start()
    run(main())


def test_motor_get_and_set():
    async def main():
        link, hub, ev, w = await make()
        r = await link.motor_get("B")
        assert (r.duty, r.direction) == (0, "disabled")
        assert await link.motor_set_direction("B", "forward") == "forward"
        assert await link.motor_set_duty("B", 30) == 30
        assert [(f.protocol, f.data) for f in hub.received] == [
            ("MOTOR", "BGP"), ("MOTOR", "BGD"), ("MOTOR", "BDF"), ("MOTOR", "BGD"), ("MOTOR", "BP030"), ("MOTOR", "BGP")]
        assert (hub.motor_duty, hub.motor_direction) == (30, "F")
    run(main())


def test_motor_refused_unless_idle():
    async def main():
        link, hub, ev, w = await make()
        hub.mode = "C"  # the hub refuses P and D silently - the read back is the check
        with pytest.raises(CommsError, match="kept 0%, not 40%"):
            await link.motor_set_duty("B", 40)
        with pytest.raises(CommsError, match="kept disabled, not reverse"):
            await link.motor_set_direction("B", "reverse")
    run(main())


def test_motor_validation():
    async def main():
        link, hub, *_ = await make()
        # A isn't fitted - the hub would send it to motorB
        for call in (link.motor_get("A"), link.motor_set_duty("A", 10), link.motor_set_direction("A", "forward")):
            with pytest.raises(CommsError, match="Motor A is not fitted"):
                await call
        for bad in (101, -1, 1.5, True):
            with pytest.raises(CommsError, match="Duty must be"):
                await link.motor_set_duty("B", bad)
        with pytest.raises(CommsError, match="Direction must be"):
            await link.motor_set_direction("B", "up")  # type: ignore[arg-type]
        assert hub.received == []
    run(main())


def test_rtc_set():
    async def main():
        link, hub, ev, w = await make()
        assert await link.rtc_set(datetime(2026, 10, 23, 14, 30, 5)) == "ok"
        assert hub.received[-1].protocol == "RTC00" and hub.received[-1].data == "S20261023143005"
        assert hub.clock == "20261023143005"
        assert await link.rtc_set(datetime(2100, 1, 1)) == "refused"  # the hub holds 2000..2099
        assert hub.clock == "20261023143005"
        hub.handle_rtc = lambda _data: None  # firmware without RTC00: a plain ACK_OK
        assert await link.rtc_set(datetime(2026, 10, 23)) == "noSocket"
    run(main())
