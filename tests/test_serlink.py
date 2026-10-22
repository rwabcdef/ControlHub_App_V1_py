"""SerLink: acks, timeouts, one frame in flight, the Reader's answers, ping, close."""
import asyncio

from conftest import Recorder, run

from controlhub.comms.serlink.frame import Frame
from controlhub.comms.serlink.serlink import SendOptions, SerLink


def ack_for(line: str, code_or_data="900") -> str:
    f = Frame.from_string(line)
    if code_or_data == "900":
        return str(Frame(f.protocol, "A", f.roll_code, Frame.ACK_OK))
    if isinstance(code_or_data, int):
        return str(Frame(f.protocol, "A", f.roll_code, code_or_data))
    return str(Frame(f.protocol, "A", f.roll_code, len(code_or_data), code_or_data))


def test_t_frame_acked_ok_and_with_data():
    async def main():
        w = Recorder()
        link = SerLink(w)
        w.target = link
        sock = link.acquire_socket("CTRL0")
        w.respond = lambda line: [ack_for(line)]
        r = await sock.send_data("BS", True)
        assert r.status == "ok" and r.ack_data is None and w.lines == ["CTRL0T000002BS"]
        w.respond = lambda line: [ack_for(line, "0120")]
        r = await sock.send_data("BGR", True)
        assert r.status == "ok" and r.ack_data == "0120" and w.lines[-1] == "CTRL0T001003BGR"
    run(main())


def test_nack_timeout_and_u_frame():
    async def main():
        w = Recorder()
        link = SerLink(w)
        w.target = link
        sock = link.acquire_socket("CTRL0")
        w.respond = lambda line: [ack_for(line, 901)]
        assert (await sock.send_data("BX", True)).status == "nack"
        w.respond = None
        assert (await sock.send_data("BX", True)).status == "timeout"
        assert (await sock.send_data("BX", False)).status == "ok"  # 'U': no ack awaited
        assert w.lines[-1][5] == "U"
    run(main())


def test_wrong_roll_code_or_type_does_not_complete():
    async def main():
        w = Recorder()
        link = SerLink(w)
        w.target = link
        sock = link.acquire_socket("CTRL0")
        w.respond = lambda line: ["CTRL0A777900", "LIFT0A000900", "CTRL0B000900"]
        assert (await sock.send_data("BX", True)).status == "timeout"
    run(main())


def test_one_frame_in_flight():
    async def main():
        w = Recorder()
        link = SerLink(w)
        w.target = link
        sock = link.acquire_socket("CTRL0")
        first = asyncio.ensure_future(sock.send_data("BGA", True))
        second = asyncio.ensure_future(sock.send_data("BGM", True))
        await asyncio.sleep(0.01)
        assert w.lines == ["CTRL0T000003BGA"]  # BGM waits for BGA's ack
        link.receive_line(ack_for(w.lines[0]))
        await asyncio.sleep(0.01)
        assert w.lines == ["CTRL0T000003BGA", "CTRL0T001003BGM"]
        link.receive_line(ack_for(w.lines[1]))
        assert (await first).status == "ok" and (await second).status == "ok"
    run(main())


def test_received_t_is_acked_before_delivery_and_u_is_not_acked():
    async def main():
        w = Recorder()
        link = SerLink(w)
        got = []

        def on_receive(f):
            got.append(f.data)
            if f.data == "abc":
                asyncio.ensure_future(sock.send_data("reply", False))

        sock = link.acquire_socket("LIFT0", on_receive)
        link.receive_line("LIFT0T123003abc")
        await asyncio.sleep(0.01)
        assert got == ["abc"]
        assert w.lines == ["LIFT0A123900", "LIFT0U000005reply"]  # the ack goes first
        link.receive_line("LIFT0U124003def")
        await asyncio.sleep(0.01)
        assert got == ["abc", "def"] and len(w.lines) == 2
        link.receive_line("XXXXXU001001z")  # no socket: dropped
        assert got == ["abc", "def"]
        assert link.receive_line("not a frame") is False
    run(main())


def test_system_ping_answers():
    async def main():
        w = Recorder()
        link = SerLink(w)
        got = []
        link.acquire_socket("LIFT0", got.append)
        link.receive_line("LIFT0S045004PING")
        link.receive_line("XXXXXS046004PING")
        link.receive_line("LIFT0S047004WHAT")
        await asyncio.sleep(0.01)
        assert w.lines == ["LIFT0A045008PINGBACK", "XXXXXA046900", "LIFT0A047900"]
        assert got == []  # 'S' is never delivered
    run(main())


def test_ping_outcomes():
    async def main():
        w = Recorder()
        link = SerLink(w)
        w.target = link
        sock = link.acquire_socket("LIFT0")
        w.respond = lambda line: [ack_for(line, "PINGBACK")]
        assert (await sock.ping()).result == "ok"
        assert w.lines[-1] == "LIFT0S000004PING"
        w.respond = lambda line: [ack_for(line)]
        assert (await sock.ping()).result == "noSocket"
        w.respond = lambda line: [ack_for(line, "HUH")]
        assert (await sock.ping()).result == "unexpected"
        w.respond = None
        o = await sock.ping()
        assert o.result == "timeout" and o.elapsed_ms >= 40
    run(main())


def test_relay_ack():
    async def main():
        w = Recorder()
        link = SerLink(w)
        w.target = link
        sock = link.acquire_socket("LED01")

        def both(line):
            f = Frame.from_string(line)
            return [ack_for(line), str(Frame(f.protocol, "B", f.roll_code, Frame.ACK_OK))]

        w.respond = both
        r = await sock.send_data("A1", True, SendOptions(relay_ack=True))
        assert r.status == "ok" and r.ack.type == "B"
        w.respond = lambda line: [ack_for(line)]
        r = await sock.send_data("A1", True, SendOptions(relay_ack=True))
        assert r.status == "timeout" and r.ack.type == "A"
    run(main())


def test_errors_close_and_limits():
    async def main():
        w = Recorder()
        link = SerLink(w)
        sock = link.acquire_socket("CTRL0")
        assert (await sock.send_data("x" * 65, True)).status == "error"
        w.fail = OSError("port gone")
        r = await sock.send_data("BS", True)
        assert r.status == "error" and "port gone" in str(r.error)
        w.fail = None
        pending = asyncio.ensure_future(sock.send_data("BS", True))
        await asyncio.sleep(0.01)
        link.close()
        assert (await pending).status == "closed"
        assert (await sock.send_data("BS", True)).status == "closed"
        try:
            link.acquire_socket("TOO_LONG")
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
    run(main())
