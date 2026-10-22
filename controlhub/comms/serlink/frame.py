"""SerLink frame, as the ControlHubAA26 firmware's SerLink::Frame (Middlewares/SerLink/Frame).

    <protocol:5><type:1><rollCode:3><dataLen:3><data:dataLen>
    e.g. CTRL0U001008030.0350

On an ack ('A' / 'B') dataLen may instead be a status code (>= ACK_OK), in which
case there is no data, e.g. LED01A492900. An ack can also piggyback data
instead, e.g. CTRL0A5290040120.

'S' is a system request, to the SerLink layer rather than the socket's owner,
e.g. LIFT0S045004PING. It is always answered with an ordinary 'A'
(LIFT0A045008PINGBACK), never with another 'S' - see serlink.py.

Lines are '\\n' terminated on the wire; __str__() / from_string() work on the
line without its terminator (the link adds / strips it).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_PROTOCOL_RE = re.compile(r"^[\x21-\x7e]{5}$")
_DIGITS3_RE = re.compile(r"^\d{3}$")


@dataclass(frozen=True)
class Frame:
    TYPE_TRANSMISSION = "T"
    TYPE_UNIDIRECTION = "U"
    TYPE_ACK = "A"
    TYPE_RELAY_ACK = "B"
    TYPE_SYSTEM = "S"
    """System request, answered with an 'A' - as the firmware's Frame::TYPE_SYSTEM"""

    LEN_PROTOCOL = 5
    LEN_TYPE = 1
    LEN_ROLLCODE = 3
    LEN_DATALEN = 3
    LEN_HEADER = 12
    INDEX_START_TYPE = 5
    INDEX_START_ROLLCODE = 6
    INDEX_START_DATALEN = 9
    INDEX_START_DATA = 12
    MAX_DATALEN = 64

    ACK_OK = 900
    """dataLen (ack status) return code"""

    TYPES = frozenset("TUABS")

    protocol: str
    type: str
    roll_code: int = 0
    data_len: int = 0
    """Length of data, or an ack status code (>= ACK_OK)"""
    data: str = ""

    def is_status(self) -> bool:
        """True if data_len is an ack status code rather than a data length."""
        return self.data_len >= Frame.ACK_OK

    def is_ack(self) -> bool:
        return self.type in (Frame.TYPE_ACK, Frame.TYPE_RELAY_ACK)

    @staticmethod
    def from_string(raw: str) -> Frame | None:
        """Parse one line (terminator optional). Unlike the firmware's fromString(),
        the header is validated: returns None for anything that isn't a SerLink
        frame, so other line formats can share the link. Data beyond dataLen is
        ignored; data shorter than dataLen is rejected."""
        line = raw[:-2] if raw.endswith("\r\n") else raw[:-1] if raw.endswith("\n") else raw
        if len(line) < Frame.LEN_HEADER:
            return None

        protocol = line[: Frame.LEN_PROTOCOL]
        ftype = line[Frame.INDEX_START_TYPE]
        roll_str = line[Frame.INDEX_START_ROLLCODE: Frame.INDEX_START_DATALEN]
        len_str = line[Frame.INDEX_START_DATALEN: Frame.INDEX_START_DATA]
        if not _PROTOCOL_RE.match(protocol) or ftype not in Frame.TYPES:
            return None
        if not _DIGITS3_RE.match(roll_str) or not _DIGITS3_RE.match(len_str):
            return None

        roll_code = int(roll_str)
        data_len = int(len_str)
        if data_len >= Frame.ACK_OK:
            return Frame(protocol, ftype, roll_code, data_len)

        data = line[Frame.INDEX_START_DATA: Frame.INDEX_START_DATA + data_len]
        if len(data) != data_len:
            return None
        return Frame(protocol, ftype, roll_code, data_len, data)

    def __str__(self) -> str:
        header = f"{self.protocol}{self.type}{self.roll_code:03d}{self.data_len:03d}"
        return header if self.is_status() else header + self.data

    @staticmethod
    def next_roll_code(roll_code: int) -> int:
        """Same wraparound as the firmware's Frame::incRollCode(): 0..998."""
        nxt = roll_code + 1
        return 0 if nxt >= 999 else nxt
