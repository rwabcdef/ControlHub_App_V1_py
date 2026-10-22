"""Candidate 3: NiceGUI (Vue + Quasar, served from Python, shown in a native
pywebview window). Gauges and strip charts are ECharts (bundled with NiceGUI);
the speed dial is a small custom Vue/SVG component (nicegui_speed_dial.js),
since no library ships a draggable knob with SpeedDial's rules.

The Python side is a server: the UI lives in a browser engine and every update
crosses a websocket. So the gauges are pushed at 20 Hz and the charts at 10 Hz
(the header shows both rates and the browser's own frame rate).

Run:  .venv\\Scripts\\python nicegui_demo.py            (native window)
      .venv\\Scripts\\python nicegui_demo.py --browser  (in your browser, http://127.0.0.1:8090)
"""
from __future__ import annotations

import sys

import numpy as np
from nicegui import ui
from nicegui.element import Element

from common import geometry as g
from common.sim import CURRENT_MAX, DIAL_RPM_MAX, RPM_MAX, SCENARIOS, WINDOW_SEC, FpsMeter, HubSim

sim = HubSim()
push_rate = FpsMeter()


class SpeedDial(Element, component="nicegui_speed_dial.js"):
    def __init__(self, max_: int, label: str, unit: str, color: str, on_change):
        super().__init__()
        self._props.update(value=None, min=0, max=max_, mode="edit", color=color, label=label, unit=unit)
        self.on("change", lambda e: on_change(int(e.args)))

    def set_view(self, value: int | None, mode: str):
        if (self._props["value"], self._props["mode"]) != (value, mode):
            self._props["value"], self._props["mode"] = value, mode
            self.update()


# --------------------------------------------------------------------------- ECharts options
def gauge_options(hi: float, label: str, color: str, warn=None, danger=None, split=6) -> dict:
    """Gauge.tsx in ECharts: a 240 degree scale (210 -> -30), progress arc, warn / danger bands."""
    common = {"type": "gauge", "startAngle": 210, "endAngle": -30, "min": 0, "max": hi, "splitNumber": split,
              "radius": "92%", "center": ["50%", "58%"]}
    bands = [[1, "transparent"]]
    if warn is not None:
        bands = [[warn / hi, "transparent"], [(danger or hi) / hi, g.WARN], [1, g.DANGER if danger else g.WARN]]
    return {
        "animation": False,
        "series": [
            {**common,
             "progress": {"show": True, "width": 6, "itemStyle": {"color": color}},
             "axisLine": {"lineStyle": {"width": 6, "color": [[1, g.TRACK]]}},
             "axisTick": {"distance": 2, "splitNumber": 4, "length": 5, "lineStyle": {"color": g.TEXT_2, "width": 0.8}},
             "splitLine": {"distance": 2, "length": 10, "lineStyle": {"color": g.TEXT_2, "width": 1.5}},
             "axisLabel": {"distance": 16, "color": g.TEXT_2, "fontSize": 10},
             "pointer": {"length": "72%", "width": 3, "itemStyle": {"color": color}},
             "anchor": {"show": True, "size": 10, "itemStyle": {"color": g.PAPER, "borderColor": color, "borderWidth": 2}},
             "title": {"offsetCenter": [0, "62%"], "color": g.TEXT_2, "fontSize": 11},
             "detail": {"offsetCenter": [0, "36%"], "fontSize": 24, "fontWeight": 600, "color": g.TEXT},
             "data": [{"value": 0, "name": label}]},
            {**common, "radius": "84%",  # the warn / danger bands, just inside the scale
             "axisLine": {"lineStyle": {"width": 2, "color": bands}},
             "axisTick": {"show": False}, "splitLine": {"show": False}, "axisLabel": {"show": False},
             "pointer": {"show": False}, "detail": {"show": False}, "title": {"show": False}, "data": []},
        ],
    }


def chart_options(color: str, y_name: str, y_range=None) -> dict:
    axis = {"axisLine": {"lineStyle": {"color": g.DIVIDER}}, "axisLabel": {"color": g.TEXT_2, "fontSize": 11},
            "splitLine": {"lineStyle": {"color": "#232a33"}}}
    y = {"type": "value", "name": y_name, "nameLocation": "middle", "nameGap": 38,
         "nameTextStyle": {"color": g.TEXT_2}, **axis}
    y.update({"min": y_range[0], "max": y_range[1]} if y_range else {"scale": True})
    return {
        "animation": False,
        "grid": {"left": 52, "right": 14, "top": 10, "bottom": 26},
        "xAxis": {"type": "value", "min": 0, "max": WINDOW_SEC, "interval": 1, **axis,
                  "axisLabel": {"color": g.TEXT_2, "fontSize": 11, ":formatter": "v => Math.round(v * 10) / 10"}},
        "yAxis": y,
        "series": [{"type": "line", "showSymbol": False, "data": [], "lineStyle": {"width": 1.5, "color": color},
                    "itemStyle": {"color": color}}],
    }


# --------------------------------------------------------------------------- small pieces
def panel(title: str | None = None):
    card = ui.element("div").classes("flex flex-col gap-2 p-3 rounded-md min-w-0").style(
        f"background:{g.PAPER}; border:1px solid {g.DIVIDER}")
    with card:
        title_row = ui.row().classes("w-full items-center no-wrap")
        if title:
            with title_row:
                ui.label(title).classes("text-sm font-semibold grow").style(f"color:{g.TEXT_2}")
    return card, title_row


class CmdButton:
    """A MUI-style button: spinner while its command is in flight; the tooltip says why it's disabled
    (on a wrapper, since a disabled button gets no pointer events)."""

    def __init__(self, label: str, icon: str, which: str, on_click, in_row: bool = False):
        self.which = which
        with ui.element("div").classes("flex-1 min-w-0" if in_row else "w-full") as self.wrap:
            self.btn = ui.button(label, icon=icon, on_click=on_click).props("unelevated no-caps dense").classes("w-full")
            self.tip = ui.tooltip("")
        self._state = None

    def refresh(self, busy: str | None, reason: str):
        state = (busy == self.which, bool(reason) or (busy is not None and busy != self.which), reason)
        if state == self._state:
            return
        self._state = state
        loading, disabled, _ = state
        if loading:
            self.btn.props("loading")
        else:
            self.btn.props(remove="loading")
        self.btn.set_enabled(not disabled)
        self.tip.text = reason
        self.tip.set_visibility(bool(reason))


# --------------------------------------------------------------------------- the page
@ui.page("/")
def index():
    ui.dark_mode(True)
    ui.colors(primary=g.PRIMARY, positive=g.SUCCESS)
    ui.query("body").style(f"background:{g.BG}; font-family: 'Segoe UI', system-ui, sans-serif")
    # A full-height app shell, no page scroll (NiceGUI's content column has padding by default)
    ui.query(".nicegui-content").classes("h-screen p-0 gap-0 no-wrap overflow-hidden")
    ui.add_body_html("""<script>
      (() => { let n = 0, t = performance.now();
        const f = () => { n++; const now = performance.now();
          if (now - t > 1000) { const el = document.getElementById('bfps');
            if (el) el.textContent = Math.round(n * 1000 / (now - t)) + ' fps browser'; n = 0; t = now; }
          requestAnimationFrame(f); };
        requestAnimationFrame(f); })();
    </script>""")

    # ---- header (MainLayout.tsx) + the demo's sim controls
    with ui.row().classes("w-full items-center px-3 py-1 gap-3 no-wrap").style(f"border-bottom:1px solid {g.DIVIDER}"):
        ui.html(f"<b style='font-size:16px'>ControlHub</b> <span style='color:{g.TEXT_2};font-size:16px'>AA26</span>")
        ui.space()
        ui.label("Sim:").style(f"color:{g.TEXT_2}")
        scenario = ui.select(SCENARIOS, value=SCENARIOS[0], on_change=lambda e: sim.set_scenario(e.value)) \
            .props("dense outlined options-dense").classes("w-52")
        ui.button("Remote button 1", on_click=sim.remote_button).props("outline no-caps dense").classes("px-2") \
            .tooltip("Start / stop a run as the remote hub would")
        rates = ui.label().classes("text-xs w-40").style(f"color:{g.TEXT_2}")
        ui.html('<span id="bfps" class="text-xs"></span>').style(f"color:{g.TEXT_2}").classes("w-24")
        ui.chip("SIM · connected", color="positive").props("dense").classes("text-black")
    with ui.tabs().props("dense align=left active-color=primary indicator-color=primary no-caps").classes("w-full") \
            .style(f"border-bottom:1px solid {g.DIVIDER}; color:{g.TEXT_2}"):
        for t in ("Dashboard", "Config", "MQTT log", "Files", "Dev"):
            ui.tab(t)

    with ui.row().classes("w-full no-wrap gap-3 p-3 items-stretch grow min-h-0"):
        # ---- DashboardControl.tsx
        card, title_row = panel("Control")
        card.classes("w-[210px] shrink-0")
        with title_row:
            chip = ui.chip("Idle").props("dense outline")
        with card:
            ui.label("CONTROL").classes("text-[11px] tracking-widest").style(f"color:{g.TEXT_2}")
            direction = ui.select({"forward": "Forward", "reverse": "Reverse"}, value="forward",
                                  on_change=lambda e: e.value != sim.direction and sim.set_direction(e.value)) \
                .props("dense outlined options-dense").classes("w-full")
            start = CmdButton("Start", "play_arrow", "start", sim.start)
            with ui.element("div").classes("w-full h-[140px]"):
                dial = SpeedDial(DIAL_RPM_MAX, "Target", "RPM", g.SERIES["rpm"], sim.set_rpm).classes("w-full h-full")
                dial_tip = ui.tooltip("")
            ui.separator()
            ui.label("LIFT").classes("text-[11px] tracking-widest").style(f"color:{g.TEXT_2}")

            def set_move_mode(m):
                sim.move_mode = m
                updown.set_visibility(m == "upDown")
                forrev.set_visibility(m == "forRev")

            ui.select({"upDown": "Up/Down", "forRev": "For/Rev"}, value="upDown", on_change=lambda e: set_move_mode(e.value)) \
                .props("dense outlined options-dense").classes("w-full")
            with ui.row().classes("w-full no-wrap gap-2") as updown:
                up = CmdButton("Up", "arrow_upward", "up", sim.lift_up, in_row=True)
                down = CmdButton("Down", "arrow_downward", "down", sim.lift_down, in_row=True)
            with ui.column().classes("w-full gap-2") as forrev:
                ui.select({"forward": "Forward", "reverse": "Reverse"}, value="forward",
                          on_change=lambda e: setattr(sim, "lift_direction", e.value)) \
                    .props("dense outlined options-dense").classes("w-full")
                move = CmdButton("Start", "play_arrow", "move", sim.lift_move)
            forrev.set_visibility(False)
            lift_caption = ui.label().classes("w-full text-center text-xs").style(f"color:{g.TEXT_2}")
            with ui.row().classes("w-full justify-center items-center gap-2 py-1 rounded-md") as lamp:
                lamp_dot = ui.element("div").classes("w-3 h-3 rounded-full")
                lamp_text = ui.label("Done").classes("font-semibold text-sm")
            progress = ui.label().classes("w-full text-center text-xs").style(f"color:{g.TEXT_2}")
            ui.separator()
            stop = CmdButton("Stop", "stop", "stop", sim.stop)

        # ---- DashboardPage.tsx
        with ui.column().classes("grow min-w-0 gap-3 h-full no-wrap"):
            gauges = {}
            with ui.row().classes("w-full no-wrap gap-3 h-[224px] shrink-0"):
                for field, title, opts in (
                    ("rpm", "Speed", gauge_options(RPM_MAX, "Speed (RPM)", g.SERIES["rpm"], RPM_MAX * 0.8, RPM_MAX * 0.93)),
                    ("duty", "PWM duty cycle", gauge_options(100, "Duty (%)", g.SERIES["duty"], split=5)),
                    ("current", "Current", gauge_options(CURRENT_MAX, "Current (A)", g.SERIES["current"],
                                                         CURRENT_MAX * 0.7, CURRENT_MAX * 0.9, split=5)),
                ):
                    c, _ = panel(title)
                    c.classes("grow basis-0 h-full")
                    with c:
                        gauges[field] = ui.echart(opts).classes("w-full").style("height:170px")
            charts = {}
            with ui.grid(columns=2).classes("w-full grow gap-3 min-h-0").style("grid-template-rows: 1fr 1fr"):
                for field, label, yname, yr, span in (("rpm", "Speed (RPM)", "RPM", None, "col-span-2"),
                                                      ("duty", "PWM duty (%)", "%", (0, 100), ""),
                                                      ("current", "Current (A)", "A", None, "")):
                    c, _ = panel()
                    c.classes(f"{span} min-h-0 h-full")
                    with c:
                        with ui.row().classes("w-full items-center gap-2 px-1"):
                            ui.element("div").classes("w-3 h-[3px] rounded").style(f"background:{g.SERIES[field]}")
                            ui.label(label).classes("text-xs grow").style(f"color:{g.TEXT_2}")
                            ui.label("t (s)").classes("text-xs").style(f"color:{g.TEXT_DISABLED}")
                        charts[field] = ui.echart(chart_options(g.SERIES[field], yname, yr)) \
                            .classes("w-full grow").style("height:auto; min-height:0")

    last = {"done": None, "chip": None, "dir": None, "scenario": None, "tip": None}

    def push_gauges():
        decimals = {"rpm": 0, "duty": 1, "current": 2}
        for k, ch in gauges.items():
            v = round(sim.latest(k) or 0.0, decimals[k])
            # The whole data item: a value alone would drop its name (the "Speed (RPM)" caption)
            name = ch.options["series"][0]["data"][0]["name"]
            ch.run_chart_method("setOption", {"series": [{"data": [{"value": v, "name": name}]}]})

    def push_charts():
        push_rate.frame()
        t_max = max(WINDOW_SEC, sim.now())
        for k, ch in charts.items():
            t, y = sim.history(k)
            i = int(np.searchsorted(t, t_max - WINDOW_SEC - 0.1))
            t, y = t[i:], y[i:]
            if len(t) > 250:  # the websocket, not the chart, is the bottleneck: send ~250 points
                step = len(t) // 250 + 1
                t, y = t[::step], y[::step]
            data = np.round(np.column_stack((t, y)), 3).tolist()
            ch.run_chart_method("setOption", {"xAxis": {"min": t_max - WINDOW_SEC, "max": t_max},
                                              "series": [{"data": data}]})

    def refresh_controls():
        s = sim
        label, role = s.mode_chip()
        if last["chip"] != (label, role):
            last["chip"] = (label, role)
            chip.text = label
            chip.props(f"color={'positive' if role == 'success' else 'info' if role == 'info' else 'grey'}")
            if role == "default":
                chip.props("outline")
            else:
                chip.props(remove="outline")
        if last["dir"] != s.direction:
            last["dir"] = s.direction
            direction.value = s.direction
        direction.set_enabled(not s.start_blocked() and s.busy is None)
        start.refresh(s.busy, s.start_blocked())
        for b in (up, down, move):
            b.refresh(s.busy, s.lift_blocked())
        stop.refresh(s.busy, "")
        d = s.dial()
        dial.set_view(d.value, d.state)
        if last["tip"] != d.tooltip:
            last["tip"] = d.tooltip
            dial_tip.text = d.tooltip
            dial_tip.set_visibility(bool(d.tooltip))
        lift_caption.text = s.lift_caption()
        progress.text = s.lift_progress()
        if last["done"] != s.done:
            last["done"] = s.done
            on = s.done
            lamp.style(f"border:1px solid {g.SUCCESS if on else g.DIVIDER}")
            lamp_dot.style(f"background:{g.SUCCESS if on else '#3a4049'}; box-shadow:{'0 0 6px ' + g.SUCCESS if on else 'none'}")
            lamp_text.style(f"color:{g.SUCCESS if on else g.TEXT_DISABLED}")
        if last["scenario"] != s.scenario:
            last["scenario"] = s.scenario
            scenario.value = s.scenario
        rates.text = f"server: gauges 20 Hz, charts {push_rate.text().split(' ·')[0].replace(' fps', ' Hz')}"

    ui.timer(0.02, sim.step)
    ui.timer(0.05, push_gauges)
    ui.timer(0.1, push_charts)
    ui.timer(0.1, refresh_controls)


if __name__ in {"__main__", "__mp_main__"}:
    browser = "--browser" in sys.argv
    # host: NiceGUI otherwise listens on every interface, i.e. the LAN can drive the motor
    ui.run(title="ControlHub AA26 — NiceGUI demo", host="127.0.0.1", port=8090, reload=False, dark=True, show=browser,
           native=not browser, window_size=None if browser else (1280, 800))
