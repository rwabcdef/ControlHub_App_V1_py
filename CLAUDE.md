# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A PySide6 (Qt Widgets) desktop app for the **ControlHubAA26** hub. It is a port of the
Electron app in `../v1`: same pages, same rules, minus v1's right-hand "Motor control"
panel. The hub firmware lives at
`C:\Users\rwabc\Software\Projects\ControlHubAA26\Embedded\V1\ControlHubAA26_V1\`.
**Its `sockets_summary.txt` is the protocol contract**, and `Core/Src/main_tasks.cpp`
lists every frame format. `framework_demos/` is the earlier toolkit comparison; the app
doesn't use it.

## Commands

```bat
.venv\Scripts\python -m controlhub [--debug]     run (--debug: SerLink trace to the console)
.venv\Scripts\python -m pytest                   the check after every change
.venv\Scripts\pyinstaller controlhub.spec --noconfirm   dist\ControlHub\ControlHub.exe
```

The tests cover the protocol layer, settings and fs_access; nothing tests the UI. For a
UI change, run the app. Never start the real motor or lift without the user's go-ahead:
use the simulator source, or a fake hub (see `tests/conftest.py` `FakeHub`).

## Architecture

- **`controlhub/comms/` is plain asyncio, with no Qt** (except `serial_transport.py`,
  which uses QSerialPort, and `hub.py`, which is a QObject):
  - `serlink/` is a port of SerLink: `Frame`, plus `SerLink`/`Socket`/`_Writer`. A
    received `'T'` is ACK_OK'd before delivery. `'S'` PING is answered with an `'A'`.
    One frame is in flight at a time, with a 1000 ms ack timeout. The Writer registers
    its ack waiter *before* writing, and switches `'A'`→`'B'` for relays inside
    `on_ack`, because an answer can arrive within the same write/payload.
  - `hub_link.py` handles the CTRL0 reads (BGA/BGM/BGD/BGO), and sets with read-back
    checks (BI/BR/BM → BGI/BGR/BGM). When a status frame shows the mode has changed,
    it reads BGO to learn the run's source. It also handles MOTOR (the Direct page:
    `<id>P<ddd>` / `<id>D<F|R|D>`, read back with `<id>GP` / `<id>GD`), LIFT0
    (`'U'` frames, MQTT only) and RTC00 (the hub's clock: `S<yyyymmddhhmmss>`, answered
    `S1`/`S0` on the ack; `G` reads it, for the Dev page's hub clock panel).
  - `hub.py` sets the hub's clock to the PC's local time once per app run
    (`_hub_clock_loop`, setting `set_hub_time_on_launch`, on by default, on Config →
    ControlHub). It tries when a connection opens and every 10 s after that, until the
    hub answers (`S1`; `S0` or no socket also end it). The hub has no clock battery.
  - `parser.py` decodes the CTRL0 status `<I|C|L><F|R><ddd>.<rpm>.<mA>[.<run target>]`
    and the LIFT0 status.
  - `mqtt_transport.py` runs paho-mqtt on its own thread. Every callback hops to the
    loop with `call_soon_threadsafe`, so SerLink only ever runs on the UI thread. It
    resubscribes on every connect (paho doesn't do this itself).
- **`qasync`** runs asyncio on Qt's event loop. UI slots start coroutines with
  `asyncutil.spawn(coro, on_error, on_done)`.
- **`context.py`** builds everything once: `CommsHub` (it owns the transport and emits
  `state_changed`/`hub_state`/`lift_status`/`mqtt_log`), the stores in
  `state/stores.py` (Hub, Ctrl incl. the coalescing `set_rpm_live`, Direct with the
  same coalescing per motor in `set_duty_live`, Lift, ControlHub, Display), `MqttLogStore`, and `FrameClock`.
- **High-rate data never goes through signals.** `state/telemetry.py` is numpy ring
  buffers with a `version` counter. `FrameClock` fires `frame` at about 60 Hz, and only
  when the version has changed; the gauges and charts redraw from the arrays then.
- **The UI** is `ui/main_window.py` (the shell) and `ui/pages/*`. Reusable pieces are in
  `ui/widgets/`: `gauge.py` (Gauge, and SpeedDial with edit / disabled / readonly
  modes), `strip_chart.py` (pyqtgraph), and `chrome.py` (Panel, Chip, Lamp, CmdButton
  with spinner and a "why disabled" tooltip, Alert, Field). Styling is one stylesheet,
  `ui/theme.py`; variants are dynamic properties (`variant`, `tone`, `invalid`). In
  stylesheets, use `.QWidget` (exact class) for plain containers: `QWidget` would match
  every widget, buttons included.

## Direct page

`ui/pages/direct.py` drives the hub's motors open loop through its MOTOR socket, with a
duty dial and a Forward/Reverse switch per motor. The hub takes P and D only while Idle
and silently refuses them otherwise, so every set is read back. Pressing the pressed
direction again sends `D` (coast). Stop (enabled once a duty above 0 has been asked for)
sends 0% through the same coalescing slot as the dial, so unsent dial values are dropped,
and resets the dial's own value. A run or lift move leaves the bridge at 0% with no
direction, so `DirectStore` reads it again whenever the hub returns to Idle. Only the
motors in `MOTORS_FITTED` (`types.py`, currently B) are live. The hub sends selector A
to motorB until motorA exists, so A's section is drawn but disabled.

## Shutdown (easy to break)

The app ends when `run()` in `__main__.py` returns, not when Qt quits
(`setQuitOnLastWindowClosed(False)`). `MainWindow.closeEvent` disconnects, cancels
spawned tasks, then sets `finished`. The window (the context's QObjects are its
children) is deleted while the loop still runs, then `app.shutdown()` runs. pyqtgraph's
`exitCleanup` is off. Each of these fixed a crash on exit (a Qt quit stops qasync before
pending coroutines finish; GC-order teardown crashes PySide6; `os._exit` crashes in
Qt's DLL detach).

## Conventions

- Frame formats change together with the firmware. Keep the docstrings' example frames
  and digit widths: they are what keeps the app in step.
- User-facing errors are `CommsError` (comms) or `FsError` (files); `str()` is the message.
- settings.json uses v1's camelCase keys (`settings.py` maps them).
