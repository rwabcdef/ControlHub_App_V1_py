"""Payload decoders: the hub's CTRL0 / LIFT0 data, plus plain JSON / CSV telemetry lines.

Frame formats are a contract with the firmware (main_tasks.cpp, sockets_summary.txt):
change them here and in the hub together.
"""
from __future__ import annotations

import json
import math
import re

from ..types import HubMode, HubSource, HubState, LiftStatus, RawSample


def _num(v: object) -> float:
    """JS Number(): float, or NaN."""
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return math.nan


def parse_line(raw: str) -> RawSample | None:
    """Decode one line of plain (non-SerLink) telemetry. SerLink frames are handled by
    HubLink first. Accepted formats:
        JSON: {"rpm":1500,"duty":42.5,"current":1.23,"t":123456}   (t optional, ms)
        CSV:  1500,42.5,1.23[,123456]                              (rpm,duty,current[,t_ms])
    """
    line = raw.strip()
    if not line:
        return None

    if line.startswith("{"):
        try:
            o = json.loads(line)
        except ValueError:
            return None
        if not isinstance(o, dict):
            return None
        rpm, duty, current = _num(o.get("rpm")), _num(o.get("duty")), _num(o.get("current"))
        if not all(math.isfinite(v) for v in (rpm, duty, current)):
            return None
        t = _num(o.get("t"))
        return RawSample(rpm, duty, current, t if math.isfinite(t) else None)

    parts = [_num(p) for p in re.split(r"[,;\s]+", line)]
    if len(parts) < 3 or not all(math.isfinite(v) for v in parts[:3]):
        return None
    t = parts[3] if len(parts) > 3 and math.isfinite(parts[3]) else None
    return RawSample(parts[0], parts[1], parts[2], t)


_HUB_MODES: dict[str, HubMode] = {"I": "idle", "C": "control", "L": "lift"}
_STATUS_RE = re.compile(r"^([ICL])([FR])(\d{3})\.(\d{4})\.(\d{4})(?:\.(\d{4}))?$")
_HUB_MODE_RE = re.compile(r"^([ICL])([PR-])$")
_LIFT_RE = re.compile(r"^([A-Z])([MIG])(\d{6})\.(\d{6})$")


def parse_ctrl_status(data: str) -> tuple[RawSample, HubState] | None:
    """Data of the hub's CTRL0 status frame, e.g. CF030.0350.1234.0150 from
    CTRL0U001020CF030.0350.1234.0150:
        <mode I|C|L><direction F|R><duty %:3>.<measured rpm:4>.<current mA:4>.<run target rpm:4>
    Sent on MQTT every 250 ms while the hub runs (Control or Lift), and once when it
    goes idle. The sample's current is in A. The run target (the remote's pot in a
    remote run) is missing from older firmware's frames."""
    m = _STATUS_RE.match(data)
    if not m:
        return None
    hub = HubState(mode=_HUB_MODES[m[1]], direction="reverse" if m[2] == "R" else "forward",
                   run_rpm=int(m[6]) if m[6] is not None else None)
    return RawSample(rpm=int(m[4]), duty=int(m[3]), current=int(m[5]) / 1000), hub


def parse_hub_mode(data: str) -> tuple[HubMode, HubSource] | None:
    """BGO's answer, e.g. CP: <mode I|C|L><source P|R|->."""
    m = _HUB_MODE_RE.match(data)
    if not m:
        return None
    source: HubSource = "pc" if m[2] == "P" else "remote" if m[2] == "R" else "none"
    return _HUB_MODES[m[1]], source


def parse_lift_status(data: str) -> LiftStatus | None:
    """Data of the hub's LIFT0 status / done frame, e.g. BI000234.000234 from
    LIFT0U001015BI000234.000234: <lift><M|I|G><travelled:6>.<target:6>.
    M: moving; I: idle; G: a Down move ended by the ground sensor (PB9), e.g.
    BG000024.000030 - done after 24 of the 30 edges allowed."""
    m = _LIFT_RE.match(data)
    if not m:
        return None
    return LiftStatus(lift=m[1], moving=m[2] == "M", travelled=int(m[3]), target=int(m[4]))
