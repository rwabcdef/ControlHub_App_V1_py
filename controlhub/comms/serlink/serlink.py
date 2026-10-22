"""SerLink for the desktop app - a port of the Electron app's SerLink.ts (itself a
port of the Arduino project's node_js SerLink), behaving as the ControlHubAA26
firmware's Reader / Writer / Socket do.

It does no I/O itself, so the same stack runs over any line-oriented link
(serial, MQTT, ...): the link hands each received line to receive_line() and
SerLink writes lines with the LineWriter it was constructed with. asyncio only
(no Qt), so it is unit-testable on its own.

    'T' received -> 'A' (ACK_OK) sent straight back, then delivered to the socket
    'U' received -> delivered to the socket
    'S' received -> answered with an 'A' straight back, never delivered
    'A' / 'B' received -> matched against the 'T' or 'S' frame being waited on

As with the firmware Writer, frames are sent one at a time: a 'T' or 'S' frame
is not followed by the next send until it has been acked or has timed out.

System frames ('S')
-------------------
Requests to the SerLink layer itself, as in the firmware (Socket.hpp, Instant
handling). The only command is PING:

    LIFT0S045004PING -> LIFT0A045008PINGBACK   a socket for LIFT0 exists
    XXXXXS045004PING -> XXXXXA045900           link up, no such socket
    (nothing)                                  link down, or the far end predates 'S'

Socket.ping() sends one; receive_line() answers the board's. The answer is
always an 'A', so two nodes that both handle 'S' cannot ping-pong, and an 'S'
frame is never delivered to the socket's on_receive.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

from .frame import Frame

LineWriter = Callable[[str], Awaitable[None]]
"""Writes one line; the terminator is added by the link."""
FrameHandler = Callable[[Frame], None]

ACK_TIMEOUT_MS = 1000
"""Same as the firmware's WRITER_ACK_TIMEOUT_MS"""
RELAY_ACK_TIMEOUT_MS = 2000
"""SERLINK_RELAY__ACK_TIMEOUT_MS (1500) plus some slack for the link"""

SendStatus = Literal["ok", "nack", "timeout", "error", "closed"]
"""ok: sent ('U' / 'B'), or acked with ACK_OK or with data. nack: acked with a status
code other than ACK_OK (see ack.data_len). error: the link failed to write the frame.
closed: SerLink was closed before the frame was sent or acked."""


@dataclass
class SendFrameResult:
    status: SendStatus
    ack: Frame | None = None
    """The 'A' (or with relay_ack, 'B') frame that completed the send"""
    ack_data: str | None = None
    """Data piggybacked on the ack, e.g. '0120' from CTRL0A5290040120"""
    error: BaseException | None = None


SYS_PING = "PING"
SYS_PINGBACK = "PINGBACK"
"""System commands and answers - as the firmware's Socket::SYS_PING / SYS_PINGBACK"""

PingResultT = Literal["ok", "noSocket", "timeout", "unexpected", "error", "closed"]
"""ok: PINGBACK - link up, and the far end has a socket for this protocol.
noSocket: plain ACK_OK - link up, but no such socket. timeout: no answer - link down,
far end not running, or it predates 'S'. unexpected: answered with neither.
error: the link failed to write. closed: SerLink closed before the answer."""


@dataclass
class PingOutcome:
    result: PingResultT
    elapsed_ms: int
    """From handing the ping to the Writer to its answer; includes time queued behind
    earlier sends, so it is not a pure round trip."""
    ack: Frame | None = None
    error: BaseException | None = None


@dataclass
class SendOptions:
    relay_ack: bool = False
    """For a 'T' frame to a relayed socket (see the firmware's SerlinkRelay): after the
    relaying hub's 'A', also wait for the far end's relay ack ('B') and complete with that."""
    ack_timeout_ms: int | None = None
    relay_ack_timeout_ms: int | None = None


class Socket:
    def __init__(self, link: SerLink, protocol: str, initial_roll_code: int,
                 on_receive: FrameHandler | None) -> None:
        self._link = link
        self.protocol = protocol
        self._roll_code = initial_roll_code
        self._on_receive = on_receive

    async def send_data(self, data: str, ack: bool, opts: SendOptions | None = None) -> SendFrameResult:
        """Send data as a 'T' frame (ack=True, completes on the ack) or a 'U' frame."""
        if len(data) > Frame.MAX_DATALEN:
            return SendFrameResult("error", error=ValueError(
                f"{self.protocol}: data longer than {Frame.MAX_DATALEN} characters"))
        ftype = Frame.TYPE_TRANSMISSION if ack else Frame.TYPE_UNIDIRECTION
        frame = Frame(self.protocol, ftype, self._roll_code, len(data), data)
        self._roll_code = Frame.next_roll_code(self._roll_code)
        return await self._link.send_frame(frame, opts)

    async def ping(self, ack_timeout_ms: int | None = None) -> PingOutcome:
        """Ping this socket's protocol at the far end with an 'S' PING frame. Never
        raises - the outcome is in `result`. Queued behind any send in progress, like
        every other frame, so a busy or dead link delays it."""
        frame = Frame(self.protocol, Frame.TYPE_SYSTEM, self._roll_code, len(SYS_PING), SYS_PING)
        self._roll_code = Frame.next_roll_code(self._roll_code)

        start = time.monotonic()
        sent = await self._link.send_frame(frame, SendOptions(ack_timeout_ms=ack_timeout_ms))
        elapsed_ms = round((time.monotonic() - start) * 1000)

        if sent.status in ("timeout", "error", "closed"):
            return PingOutcome(sent.status, elapsed_ms, error=sent.error)
        ack = sent.ack
        if ack is not None and not ack.is_status() and ack.data == SYS_PINGBACK:
            return PingOutcome("ok", elapsed_ms, ack)
        if ack is not None and ack.data_len == Frame.ACK_OK:
            return PingOutcome("noSocket", elapsed_ms, ack)
        return PingOutcome("unexpected", elapsed_ms, ack)

    def set_on_receive(self, handler: FrameHandler | None) -> None:
        self._on_receive = handler

    def deliver(self, frame: Frame) -> None:
        """Called by SerLink with the 'T' and 'U' frames received for this socket."""
        if self._on_receive is not None:
            self._on_receive(frame)


@dataclass
class _AckWaiter:
    frame: Frame
    type: str
    """The ack type awaited now: 'A', then 'B' for a relayed send"""
    future: asyncio.Future
    """Resolves with the completing ack, or None on timeout / close"""
    relay_timeout_ms: int | None = None
    """Set when a relay ack ('B') is to follow an ACK_OK 'A'"""
    first_ack: Frame | None = None
    """The relaying hub's 'A', once received"""
    timer: asyncio.TimerHandle | None = None


class _Writer:
    """Sends frames one at a time, waiting for the ack of each 'T' / 'S' frame."""

    def __init__(self, loop: asyncio.AbstractEventLoop, write: LineWriter, debug: Callable[[str], None]) -> None:
        self._loop = loop
        self._write = write
        self._debug = debug
        self._lock = asyncio.Lock()  # FIFO, like the TS promise chain
        self._waiter: _AckWaiter | None = None
        self._closed = False

    async def send(self, frame: Frame, opts: SendOptions) -> SendFrameResult:
        async with self._lock:
            return await self._transmit(frame, opts)

    def on_ack(self, ack: Frame) -> bool:
        """Called by the Reader for each 'A' / 'B' frame; False if nothing was waiting on it."""
        w = self._waiter
        if (w is None or ack.type != w.type or ack.protocol != w.frame.protocol
                or ack.roll_code != w.frame.roll_code):
            return False
        if w.relay_timeout_ms is not None and w.type == Frame.TYPE_ACK and ack.data_len == Frame.ACK_OK:
            # The relaying hub took it; now wait for the far end's 'B'. Switched here, not
            # after the sender wakes, because the 'B' can follow in the same payload.
            w.first_ack, w.type = ack, Frame.TYPE_RELAY_ACK
            if w.timer is not None:
                w.timer.cancel()
            w.timer = self._loop.call_later(w.relay_timeout_ms / 1000, self._expire, w)
            return True
        self._finish_wait(ack)
        return True

    def close(self) -> None:
        self._closed = True
        self._finish_wait(None)

    async def _transmit(self, frame: Frame, opts: SendOptions) -> SendFrameResult:
        if self._closed:
            return SendFrameResult("closed")
        # 'T' and 'S' are both answered with an 'A'; nothing else is.
        waiter = None
        if frame.type in (Frame.TYPE_TRANSMISSION, Frame.TYPE_SYSTEM):
            # Never relayed for 'S': it is answered by the node it reaches.
            relay_ms = None
            if opts.relay_ack and frame.type == Frame.TYPE_TRANSMISSION:
                relay_ms = opts.relay_ack_timeout_ms if opts.relay_ack_timeout_ms is not None else RELAY_ACK_TIMEOUT_MS
            # Set up before the write (the TS does it after): an answer can arrive while
            # the write is still in progress, and must not be missed.
            waiter = self._wait_ack(frame, opts.ack_timeout_ms if opts.ack_timeout_ms is not None
                                    else ACK_TIMEOUT_MS, relay_ms)
        self._debug(f"tx {frame}")
        try:
            await self._write(str(frame))
        except Exception as err:  # noqa: BLE001 - any link failure is reported, not raised
            if waiter is not None:
                self._finish_wait(None)
            return SendFrameResult("error", error=err)
        if waiter is None:
            return SendFrameResult("ok")

        ack = await waiter.future
        if ack is None and waiter.first_ack is not None:  # 'A' came, the relay's 'B' didn't
            return SendFrameResult("closed") if self._closed else SendFrameResult("timeout", waiter.first_ack)
        if ack is None:
            if self._closed:
                return SendFrameResult("closed")
            self._debug(f"ack timeout {frame}")
            return SendFrameResult("timeout")
        if ack.is_status():
            return SendFrameResult("ok" if ack.data_len == Frame.ACK_OK else "nack", ack)
        return SendFrameResult("ok", ack, ack.data)

    def _wait_ack(self, frame: Frame, timeout_ms: int, relay_timeout_ms: int | None) -> _AckWaiter:
        w = _AckWaiter(frame, Frame.TYPE_ACK, self._loop.create_future(), relay_timeout_ms)
        if self._closed:
            w.future.set_result(None)
            return w
        w.timer = self._loop.call_later(timeout_ms / 1000, self._expire, w)
        self._waiter = w
        return w

    def _expire(self, w: _AckWaiter) -> None:
        if self._waiter is w:
            self._finish_wait(None)

    def _finish_wait(self, ack: Frame | None) -> None:
        w = self._waiter
        if w is None:
            return
        self._waiter = None
        if w.timer is not None:
            w.timer.cancel()
        if not w.future.done():
            w.future.set_result(ack)


class SerLink:
    def __init__(self, write: LineWriter, debug: Callable[[str], None] | None = None) -> None:
        """Construct from a coroutine (or running loop): it captures the running loop."""
        self._loop = asyncio.get_running_loop()
        self._write = write
        self._debug = debug or (lambda _msg: None)
        self._sockets: dict[str, Socket] = {}
        self._writer = _Writer(self._loop, write, self._debug)
        self._pending: set[asyncio.Task] = set()

    def acquire_socket(self, protocol: str, on_receive: FrameHandler | None = None,
                       initial_roll_code: int = 0) -> Socket:
        """Acquire the socket for a protocol (5 characters, e.g. 'CTRL0'). Raises if already acquired."""
        if len(protocol) != Frame.LEN_PROTOCOL:
            raise ValueError(f'SerLink protocol must be {Frame.LEN_PROTOCOL} characters: "{protocol}"')
        if protocol in self._sockets:
            raise ValueError(f"SerLink socket {protocol} already acquired")
        socket = Socket(self, protocol, initial_roll_code, on_receive)
        self._sockets[protocol] = socket
        return socket

    def release_socket(self, socket: Socket) -> None:
        if self._sockets.get(socket.protocol) is socket:
            del self._sockets[socket.protocol]

    async def send_frame(self, frame: Frame, opts: SendOptions | None = None) -> SendFrameResult:
        """Send a complete frame, as is (roll code included). Used by Socket; also for raw frames."""
        return await self._writer.send(frame, opts or SendOptions())

    def receive_line(self, line: str) -> bool:
        """The Reader: handle one received line. Returns False if the line isn't a
        SerLink frame, so the caller can try other formats."""
        frame = Frame.from_string(line.strip())
        if frame is None:
            return False
        self._debug(f"rx {frame}")

        if frame.type == Frame.TYPE_TRANSMISSION:
            # Acked before delivery, as the firmware Reader does, so the ack always
            # precedes anything the socket sends in response. Written directly - not
            # queued behind a 'T' frame of ours that may be waiting for its own ack.
            self._write_direct(Frame(frame.protocol, Frame.TYPE_ACK, frame.roll_code, Frame.ACK_OK))
            self._deliver(frame)
        elif frame.type == Frame.TYPE_UNIDIRECTION:
            self._deliver(frame)
        elif frame.type == Frame.TYPE_SYSTEM:
            # Answered here, as the firmware's Socket::onInstant() does, and never
            # delivered. PINGBACK only if we have a socket for the protocol; otherwise,
            # and for any command we don't know, a plain ACK_OK.
            if frame.data == SYS_PING and frame.protocol in self._sockets:
                answer = Frame(frame.protocol, Frame.TYPE_ACK, frame.roll_code, len(SYS_PINGBACK), SYS_PINGBACK)
            else:
                answer = Frame(frame.protocol, Frame.TYPE_ACK, frame.roll_code, Frame.ACK_OK)
            self._write_direct(answer)
        else:  # 'A' / 'B' - e.g. the 'A' that precedes a relay's 'B', when relay_ack wasn't asked for
            if not self._writer.on_ack(frame):
                self._debug(f"unmatched ack {frame}")
        return True

    def close(self) -> None:
        """Stop sending: queued and in-flight sends complete with status 'closed'."""
        self._writer.close()
        self._sockets.clear()

    def _write_direct(self, frame: Frame) -> None:
        self._debug(f"tx {frame}")
        task = self._loop.create_task(self._write_logged(str(frame)))
        self._pending.add(task)  # keep a reference until done
        task.add_done_callback(self._pending.discard)

    async def _write_logged(self, line: str) -> None:
        try:
            await self._write(line)
        except Exception as err:  # noqa: BLE001
            self._debug(f"ack write failed: {err}")

    def _deliver(self, frame: Frame) -> None:
        socket = self._sockets.get(frame.protocol)
        if socket is not None:
            socket.deliver(frame)
        else:
            self._debug(f"no socket for {frame.protocol}")
