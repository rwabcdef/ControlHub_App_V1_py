"""Frame, the payload parsers and the status thinner, on the firmware's own example frames."""
import math

from controlhub.comms.parser import parse_ctrl_status, parse_hub_mode, parse_lift_status, parse_line
from controlhub.comms.serlink.frame import Frame
from controlhub.comms.status_thinner import StatusThinner


# ---------------------------------------------------------------- Frame
def test_frame_round_trip():
    f = Frame.from_string("CTRL0U001020CF030.0350.1234.0150\n")
    assert f == Frame("CTRL0", "U", 1, 20, "CF030.0350.1234.0150")
    assert str(f) == "CTRL0U001020CF030.0350.1234.0150"


def test_frame_ack_status_and_piggyback():
    ok = Frame.from_string("LED01A492900")
    assert ok.is_status() and ok.is_ack() and ok.data == "" and str(ok) == "LED01A492900"
    data = Frame.from_string("CTRL0A5290040120")
    assert not data.is_status() and data.data == "0120"
    assert Frame.from_string("LIFT0S045004PING").type == "S"


def test_frame_rejects_non_frames():
    for bad in ("", "hello", "1500,42.5,1.23", '{"rpm":1}', "CTRL0X001003abc", "CTRL0T0a1003abc",
                "CTRL0T001005abc", "CT L0T001003abc"):
        assert Frame.from_string(bad) is None, bad


def test_frame_extra_data_ignored_crlf_stripped():
    f = Frame.from_string("CTRL0T001003BGAxyz\r\n")
    assert f.data == "BGA"


def test_roll_code_wraps_like_firmware():
    assert Frame.next_roll_code(0) == 1
    assert Frame.next_roll_code(997) == 998
    assert Frame.next_roll_code(998) == 0


# ---------------------------------------------------------------- parsers
def test_ctrl_status_with_run_target():
    sample, hub = parse_ctrl_status("CF030.0350.1234.0150")
    assert (sample.rpm, sample.duty, sample.current) == (350, 30, 1.234)
    assert (hub.mode, hub.direction, hub.source, hub.run_rpm) == ("control", "forward", None, 150)


def test_ctrl_status_older_firmware_and_bad():
    sample, hub = parse_ctrl_status("LR100.0000.0000")
    assert hub.mode == "lift" and hub.direction == "reverse" and hub.run_rpm is None
    assert parse_ctrl_status("CF030.0350.1234.015") is None
    assert parse_ctrl_status("XF030.0350.1234") is None


def test_hub_mode():
    assert parse_hub_mode("CP") == ("control", "pc")
    assert parse_hub_mode("CR") == ("control", "remote")
    assert parse_hub_mode("I-") == ("idle", "none")
    assert parse_hub_mode("C") is None


def test_lift_status():
    s = parse_lift_status("BI000234.000234")
    assert (s.lift, s.moving, s.travelled, s.target) == ("B", False, 234, 234)
    assert parse_lift_status("BM000120.000234").moving
    assert parse_lift_status("BG000024.000030").moving is False
    assert parse_lift_status("BX000024.000030") is None


def test_plain_lines():
    s = parse_line('{"rpm":1500,"duty":42.5,"current":1.23,"t":123456}')
    assert (s.rpm, s.duty, s.current, s.t) == (1500, 42.5, 1.23, 123456)
    s = parse_line("1500,42.5,1.23")
    assert (s.rpm, s.duty, s.current, s.t) == (1500, 42.5, 1.23, None)
    assert parse_line("1500; 42.5 1.23 99").t == 99
    assert parse_line('{"rpm":"x","duty":1,"current":1}') is None
    assert parse_line("1,2") is None and parse_line("") is None and parse_line("{bad") is None
    assert not math.isnan(parse_line("0,0,0").current)


# ---------------------------------------------------------------- thinner
def test_status_thinner_keeps_1_in_10_and_idle():
    th = StatusThinner()
    run = "rx CTRL0U001020CF030.0350.1234.0150"
    kept = [th.keep(run) for _ in range(25)]
    assert kept.count(True) == 3 and kept[0] and kept[10] and kept[20]
    assert th.keep("CTRL0U001020IF000.0000.0000.0150")  # idle: always, and restarts the count
    assert th.keep(run)
    assert th.keep("CTRL0A001900") and th.keep("anything else")
