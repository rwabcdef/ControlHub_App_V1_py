# Python framework demos: the dashboard in five toolkits

The Electron PC app (`../../v1`) is to be ported to Python. Before choosing a
toolkit, this folder builds the **same Dashboard screen in each viable one**:
the Control column, the three gauges and the three strip charts, in the same
dark theme and colours. Nothing talks to the hub. `common/sim.py` is a fake hub
(telemetry at 50 Hz, HubApp's Idle / Control / Lift modes, and the Control
panel's enable/disable rules), shared by every demo, so they all behave the same.

Screenshots of each, in a remote run and a lift move, are in `screenshots/`.

## Running

```bat
cd framework_demos
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

.venv\Scripts\python qt_widgets_demo.py
.venv\Scripts\python qt_quick_demo.py
.venv\Scripts\python nicegui_demo.py            (add --browser to use your browser instead)
.venv\Scripts\python flet_demo.py               (the first run downloads the Flutter client)
.venv\Scripts\python dearpygui_demo.py
```

In each one:
- **Sim:** (header) jumps to a state: Idle, Control · PC, Control · Remote, Lift.
- **Remote button 1** starts or stops a run as the remote hub would.
- **The dial** (Target RPM) can be dragged on the scale (not the centre or the gap),
  scrolled, or keyed (arrows ±1, PgUp/PgDn ±10, Home/End) after a click on it.
  It is editable while Idle or in a PC run, a **read-only meter** of the pot's
  target in a remote run, and greyed out during a lift move.
- Start / Up / Down show a spinner for the fake 300 ms round trip, and a
  tooltip says why they're disabled.
- The header shows the frame or update rate achieved.

## What each one is

| | Toolkit | Gauges / dial | Strip charts | Process model |
|---|---|---|---|---|
| 1 | **PySide6 + Qt Widgets** | `QPainter`, hand-drawn | pyqtgraph | one process, native widgets |
| 2 | **PySide6 + Qt Quick (QML)** | QML `Shape` + items | QtCharts `ChartView` | one process, QML UI + Python backend object |
| 3 | **NiceGUI** (Vue/Quasar) | ECharts `gauge`; the dial is a custom Vue/SVG component | ECharts line | Python server + browser engine (pywebview / WebView2) over a websocket |
| 4 | **Flet 1.0** (Flutter) | `flet.canvas`, hand-drawn | `flet_charts.LineChart` | Python + separate Flutter client, control diffs over a socket |
| 5 | **Dear PyGui 2** (ImGui/ImPlot) | drawlist, redrawn every frame | ImPlot | one process, immediate mode, GPU |

## Findings (this PC, Windows 11 at 150 % scaling, Python 3.14.7)

| | Rate achieved | Looks | Notes |
|---|---|---|---|
| 1 Qt Widgets | **60–63 fps**, everything | Close; Qt stylesheet theming | Least surprise. The custom painting is ~150 lines, and the rest is standard widgets. Serial (`QSerialPort`) and MQTT on a `QThread` fit naturally. |
| 2 Qt Quick | **60 fps**, everything | **Closest to MUI** (Material style, animations) | **QtGraphs crashes on load** (PySide6 6.12 / Py 3.14, any graphics backend), so it uses QtCharts, which is deprecated but works. It needs a `QApplication`, and `useOpenGL` series draw nothing. There are more moving parts: QML ↔ Python properties and slots. |
| 3 NiceGUI | Browser renders at 60 fps; the server pushes gauges at 20 Hz and charts at ~9–10 Hz | Very close (web tech, like the current app) | Every update crosses a websocket, so live data is pushed at a lower rate (the dial runs in the browser, so it stays smooth). By default it **listens on every network interface**, so the demo pins it to 127.0.0.1; a real app must too. The dial needed hand-written JS. |
| 4 Flet | **Gauges ~17 Hz, charts ~6 Hz** (target 30 / 10) | Good (Flutter Material) | Each chart update costs ~18 ms for 120 points, because Flet serialises every point as a control. There's no gauge or knob widget. The 1.0 API is new (charts moved to `flet-charts`, renamed events), and a few layout quirks remain ("Down" wraps, axis labels clipped). |
| 5 Dear PyGui | **60 fps**, everything | "Tool-like" ImGui look | The fastest charts by far. But there are no layout managers (all sizes in pixels, recomputed on resize), it's **not DPI-aware** (the demo opts in and scales by hand, or Windows blurs it), the window title isn't UTF-8, some glyphs (▶ ■) are missing from Segoe UI, and tooltips can't go on a drawlist. |

## Recommendation

**PySide6 + Qt Widgets** for the port. It ran at a steady 60 fps with no
workarounds, it's one process, and Qt has what the rest of the app needs:
`QSerialPort`, threads for the MQTT client, file dialogs (the SD-card Files page),
and tables and logs (the MQTT log and Dev pages).

If the MUI look matters more, choose Qt Quick: the same Python backend, and it
matches the Electron app more closely. It costs a QML layer, and it's stuck on
QtCharts until QtGraphs works under PySide6.

NiceGUI is the closest visually but keeps the browser and server split that a
Python app would normally be written to avoid. Flet is too slow for the live
charts today. Dear PyGui is fast but makes ordinary forms and pages (Config,
Files) hard work.

## Files

- `common/geometry.py`: the gauge geometry from Gauge.tsx / SpeedDial.tsx (240° scale
  from 150°, the 200 × 150 view box, ticks, and pointer → value with the gap snapping
  to the nearer end), plus the theme colours.
- `common/sim.py`: the fake hub and the Control panel's rules (`dial()`, `start_blocked()`, …).
- `qt_widgets_demo.py`, `qt_quick_demo.py` + `.qml`, `nicegui_demo.py` +
  `nicegui_speed_dial.js`, `flet_demo.py`, `dearpygui_demo.py`: one per toolkit.

The demo's RPM gauge goes to 600, not the app's default 6000, so the needle
moves visibly at dial speeds (0–300).
