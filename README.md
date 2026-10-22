# ControlHub AA26: desktop app (Python)

A desktop app for the **ControlHubAA26** control hub (NUCLEO-F439ZI firmware). It shows
motor telemetry (RPM, PWM duty, current), starts and stops Control runs and lift moves,
and configures the hub's speed controller. It normally connects to the hub over **MQTT**;
a serial link (USART2 via the FTDI cable) and a built-in simulator are also available.

This is a port of the Electron app in `../v1` to **PySide6 (Qt Widgets)**. It has the
same pages and rules, with one exception: the Electron app's right-hand "Motor control"
panel was dropped, because it only sent the simulator's placeholder commands.

## Run from source

```bat
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
.venv\Scripts\python -m controlhub            (add --debug to trace every SerLink frame)
.venv\Scripts\python -m pytest                (protocol, settings and file-access tests)
```

## Build a standalone app

```bat
.venv\Scripts\pyinstaller controlhub.spec --noconfirm
```

The build goes to `dist\ControlHub\` (about 165 MB). Copy the whole folder to install;
Python isn't needed on the target PC. Run `ControlHub.exe`.

## Where things are kept

- **On the hub:** gain, max duty and target speed (read on connecting, saved from
  Config → ControlHub, and the dashboard dial).
- **`%APPDATA%\ControlHub\settings.json`:** the connection settings, the lift distance,
  the dial's maximum, granted folders, and display preferences. Set `CONTROLHUB_SETTINGS`
  to use a different file.

## Pages

| Page | What it does |
|---|---|
| Dashboard | The Control column (direction, Start, target-speed dial, lift Up/Down or For/Rev, Done, Stop), three gauges, and three scrolling charts. The dial becomes a read-only meter during a run the remote hub started. |
| Direct | Motor A and B: a duty dial and a Forward/Reverse switch each, driving the motor open loop through the hub's MOTOR socket. Only while the hub is idle. A is disabled until motorA is built. |
| Config | Communications (link, serial port, MQTT broker and topics), ControlHub (controller settings on the hub, dial max, lift distance), Display (gauge ranges, chart window). |
| MQTT log | Every MQTT line both ways, with filter, pause and follow. Status frames are thinned to 1 in 10 while running. |
| Files | Browse and edit text files in folders you grant; export the telemetry buffer as CSV. |
| Dev | Send raw data to the hub's CTRL0 and LIFT0 sockets. |

The left panel connects and disconnects, and has **Ping lift**, which runs a SerLink PING
of LIFT0 over MQTT.
