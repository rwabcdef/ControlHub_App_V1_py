"""Candidate 4: Flet 1.0 (Python driving a Flutter UI). Flet has no gauge or knob,
so both are drawn on flet.canvas (with a GestureDetector for the dial); the strip
charts are flet_charts.LineChart.

Like NiceGUI, Python and the UI are separate processes: every change is a diff
sent to the Flutter client. The loop aims at 30 Hz for the gauges and 10 Hz for
the charts; the header shows the rates actually achieved.

Run:  .venv\\Scripts\\python flet_demo.py
"""
from __future__ import annotations

import asyncio
import math

import flet as ft
import flet.canvas as cv
import flet_charts as fch
import numpy as np

from common import geometry as g
from common.sim import CURRENT_MAX, DIAL_RPM_MAX, RPM_MAX, SCENARIOS, WINDOW_SEC, FpsMeter, HubSim

rad = math.radians


# --------------------------------------------------------------------------- gauge / dial
class CanvasGauge:
    """Gauge.tsx (dial=False) or SpeedDial.tsx (dial=True) drawn on a flet canvas.

    Static shapes (track, bands, ticks, labels) are rebuilt on resize only; the
    dynamic ones (value arc, needle, knob, readout) are mutated in place.
    """

    def __init__(self, lo, hi, label, unit, color, decimals=0, warn=None, danger=None, major_ticks=6,
                 dial=False, on_change=None):
        self.lo, self.hi, self.label, self.unit, self.color = lo, hi, label, unit, color
        self.decimals, self.warn, self.danger, self.major_ticks = decimals, warn, danger, major_ticks
        self.dial, self.on_change = dial, on_change
        self.value: float | None = None
        self.mode = "edit"
        self.focused = False
        self.w = self.h = 0.0
        self.canvas = cv.Canvas(shapes=[], expand=True, on_resize=self._resize, resize_interval=50)
        if dial:
            self.control = ft.GestureDetector(
                content=self.canvas, expand=True, mouse_cursor=ft.MouseCursor.CLICK,
                on_tap_down=self._press, on_pan_start=self._press, on_pan_update=self._drag,
                on_scroll=self._scroll)
        else:
            self.control = self.canvas

    # ---- geometry
    def _xy(self, vx, vy):
        s, ox, oy = g.view_scale(self.w, self.h)
        return ox + s * vx, oy + s * vy

    def _s(self):
        return g.view_scale(self.w, self.h)[0]

    def _arc(self, r, a0, a1, color, width):
        x, y = self._xy(g.CX - r, g.CY - r)
        s = self._s()
        return cv.Arc(x, y, 2 * r * s, 2 * r * s, rad(a0), rad(max(a1 - a0, 0.01)),
                      paint=ft.Paint(color=color, stroke_width=width * s, style=ft.PaintingStyle.STROKE))

    def _resize(self, e: cv.CanvasResizeEvent):
        self.w, self.h = e.width, e.height
        self._build()

    def _build(self):
        if self.w <= 0 or self.h <= 0:
            return
        s = self._s()
        static = [self._arc(g.R + 6, g.START, g.START + g.SWEEP, g.TRACK, 6)]
        if self.warn is not None:
            static.append(self._arc(g.R + 1, g.angle(self.warn, self.lo, self.hi),
                                    g.angle(self.danger if self.danger is not None else self.hi, self.lo, self.hi), g.WARN, 2))
        if self.danger is not None:
            static.append(self._arc(g.R + 1, g.angle(self.danger, self.lo, self.hi), g.START + g.SWEEP, g.DANGER, 2))
        for t in g.ticks(self.lo, self.hi, self.major_ticks):
            static.append(cv.Line(*self._xy(t.x0, t.y0), *self._xy(t.x1, t.y1),
                                  paint=ft.Paint(color=g.TEXT_2, stroke_width=(1.5 if t.major else 0.75) * s)))
            if t.label:
                static.append(cv.Text(*self._xy(t.lx, t.ly), t.label, alignment=ft.Alignment(0, 0),
                                      style=ft.TextStyle(size=8.5 * s, color=g.TEXT_2)))
        static.append(cv.Text(*self._xy(g.CX, g.CY + 42), f"{self.label} ({self.unit})", alignment=ft.Alignment(0, 0),
                              style=ft.TextStyle(size=9 * s, color=g.TEXT_2)))
        self.value_arc = self._arc(g.R + 6, g.START, g.START, self.color, 6)
        self.needle = cv.Line(0, 0, 0, 0, paint=ft.Paint(color=self.color, stroke_width=2.5 * s,
                                                         stroke_cap=ft.StrokeCap.ROUND))
        self.hub = cv.Circle(*self._xy(g.CX, g.CY), 5 * s, paint=ft.Paint(color=g.PAPER))
        self.hub_ring = cv.Circle(*self._xy(g.CX, g.CY), 5 * s,
                                  paint=ft.Paint(color=self.color, stroke_width=2 * s, style=ft.PaintingStyle.STROKE))
        dynamic = [self.value_arc, self.needle, self.hub, self.hub_ring]
        if self.dial:
            self.knob = cv.Circle(0, 0, 7 * s, paint=ft.Paint(color=g.PAPER))
            self.knob_ring = cv.Circle(0, 0, 7 * s, paint=ft.Paint(color=self.color, stroke_width=2.5 * s,
                                                                   style=ft.PaintingStyle.STROKE))
            self.focus_ring = cv.Circle(*self._xy(g.CX, g.CY), (g.R + 12) * s,
                                        paint=ft.Paint(color=ft.Colors.TRANSPARENT, stroke_width=0.8 * s,
                                                       style=ft.PaintingStyle.STROKE))
            dynamic += [self.knob, self.knob_ring, self.focus_ring]
        self.readout = cv.Text(*self._xy(g.CX, g.CY + 22), "—", alignment=ft.Alignment(0, 0),
                               style=ft.TextStyle(size=22 * s, weight=ft.FontWeight.W_600, color=g.TEXT))
        dynamic.append(self.readout)
        self.canvas.shapes = static + dynamic
        self._apply(update=False)
        self.canvas.update()

    def _apply(self, update=True):
        """Move the dynamic shapes to self.value / self.mode."""
        if not self.w:
            return
        s = self._s()
        ink = g.DISABLED_INK if self.mode == "disabled" else self.color
        f = 0.0 if self.value is None else g.frac(self.value, self.lo, self.hi)
        a = g.START + f * g.SWEEP
        new_arc = self._arc(g.R + 6, g.START, a, ink, 6)
        self.value_arc.sweep_angle = new_arc.sweep_angle if f > 0 else 0
        self.value_arc.paint = new_arc.paint
        tail = 0 if self.dial else 10
        self.needle.x1, self.needle.y1 = self._xy(*g.polar(-tail, a)) if tail else self._xy(g.CX, g.CY)
        self.needle.x2, self.needle.y2 = self._xy(*g.polar(g.R - 6, a))
        self.needle.paint = ft.Paint(color=ink, stroke_width=2.5 * s, stroke_cap=ft.StrokeCap.ROUND)
        self.hub_ring.paint = ft.Paint(color=ink, stroke_width=2 * s, style=ft.PaintingStyle.STROKE)
        if self.dial:
            kx, ky = self._xy(*g.polar(g.R + 6, a))
            self.knob.x, self.knob.y = kx, ky
            self.knob_ring.x, self.knob_ring.y = kx, ky
            self.knob_ring.paint = ft.Paint(color=ink, stroke_width=2.5 * s, style=ft.PaintingStyle.STROKE)
            self.focus_ring.paint = ft.Paint(color=g.PRIMARY if self.focused and self.mode == "edit" else ft.Colors.TRANSPARENT,
                                             stroke_width=0.8 * s, style=ft.PaintingStyle.STROKE)
            text = "—" if self.value is None else str(int(self.value))
        else:
            text = "—" if self.value is None else f"{self.value:.{self.decimals}f}"
        self.readout.value = text
        self.readout.style = ft.TextStyle(size=22 * s, weight=ft.FontWeight.W_600,
                                          color=g.TEXT_DISABLED if self.mode == "disabled" else g.TEXT)
        if update:
            self.canvas.update()

    def set_value(self, v):
        self.value = v
        self._apply()

    def set_mode(self, value, mode):
        if (value, mode) == (self.value, self.mode):
            return
        self.value, self.mode = value, mode
        if self.dial:
            self.control.mouse_cursor = ft.MouseCursor.CLICK if mode == "edit" else ft.MouseCursor.BASIC
            self.control.update()
        self._apply()

    # ---- dial input
    def _set(self, v):
        nv = int(min(self.hi, max(self.lo, round(v))))
        if nv != self.value:
            self.value = nv
            self._apply()
            self.on_change(nv)

    def step(self, d):
        cur = self.value if self.value is not None else self.lo
        if (cur > self.hi and d > 0) or (cur < self.lo and d < 0):
            return
        self._set(cur + d)

    def _press(self, e):
        if self.mode != "edit":
            return
        self.focused = True
        p = g.point_at(e.local_position.x, e.local_position.y, self.w, self.h)
        self._dragging = bool(p and p[1] >= g.GRAB_RADIUS and p[0] <= g.SWEEP)
        if self._dragging:
            self._set(g.value_of(p[0], self.lo, self.hi))
        else:
            self._apply()

    def _drag(self, e):
        if self.mode != "edit" or not getattr(self, "_dragging", False):
            return
        p = g.point_at(e.local_position.x, e.local_position.y, self.w, self.h)
        if p:
            self._set(g.value_of(p[0], self.lo, self.hi))

    def _scroll(self, e: ft.ScrollEvent):
        if self.mode == "edit" and e.scroll_delta.y:
            self.step(1 if e.scroll_delta.y < 0 else -1)

    def key(self, key: str):
        if self.mode != "edit" or not self.focused:
            return
        k = key.replace(" ", "").lower()
        d = {"arrowup": 1, "arrowright": 1, "arrowdown": -1, "arrowleft": -1, "pageup": 10, "pagedown": -10}.get(k)
        if d is not None:
            self.step(d)
        elif k == "home":
            self._set(self.lo)
        elif k == "end":
            self._set(self.hi)


# --------------------------------------------------------------------------- chrome
def panel(content: ft.Control, title: str | None = None, action: ft.Control | None = None, **kw) -> ft.Container:
    rows = []
    if title or action:
        rows.append(ft.Row([ft.Text(title or "", color=g.TEXT_2, weight=ft.FontWeight.W_600, size=13, expand=True)]
                           + ([action] if action else [])))
    rows.append(content)
    return ft.Container(ft.Column(rows, spacing=8, expand=True), bgcolor=g.PAPER, border_radius=6,
                        border=ft.Border.all(1, g.DIVIDER), padding=12, **kw)


def chip(text: str, role: str = "default") -> ft.Container:
    c = ft.Container(ft.Text(text, size=12), border_radius=11, padding=ft.Padding.symmetric(horizontal=9, vertical=2))
    set_chip(c, text, role)
    return c


def set_chip(c: ft.Container, text: str, role: str):
    tone = {"success": g.SUCCESS, "info": "#29b6f6"}.get(role, g.DIVIDER)
    c.content.value = text
    c.content.color = g.TEXT_2 if role == "default" else "#0b1a12"
    c.bgcolor = None if role == "default" else tone
    c.border = ft.Border.all(1, tone)


class CmdButton:
    """A MUI-style button: a spinner while its command is in flight; the tooltip says why it's disabled
    (on a wrapper, as a disabled button shows none)."""

    def __init__(self, label, icon, which, on_click, expand=False):
        self.label, self.icon, self.which = label, icon, which
        self.btn = ft.FilledButton(content=label, icon=icon, on_click=lambda _: on_click(), expand=True,
                                   style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=4)))
        self.control = ft.Container(ft.Row([self.btn]), expand=expand)
        self._state = None

    def refresh(self, busy, reason) -> bool:
        state = (busy == self.which, bool(reason) or (busy is not None and busy != self.which), reason)
        if state == self._state:
            return False
        self._state = state
        loading, disabled, reason = state
        self.btn.content = ft.ProgressRing(width=16, height=16, stroke_width=2) if loading else self.label
        self.btn.icon = None if loading else self.icon
        self.btn.disabled = disabled
        self.control.tooltip = reason or None
        return True


def strip_chart(field, label, y_name, y_range=None):
    chart = fch.LineChart(
        data_series=[fch.LineChartData(points=[], color=g.SERIES[field], stroke_width=1.5, curved=False)],
        min_x=0, max_x=WINDOW_SEC, min_y=y_range[0] if y_range else None, max_y=y_range[1] if y_range else None,
        horizontal_grid_lines=fch.ChartGridLines(color="#232a33", width=1),
        vertical_grid_lines=fch.ChartGridLines(color="#232a33", width=1, interval=1),
        left_axis=fch.ChartAxis(label_size=44, title=ft.Text(y_name, size=11, color=g.TEXT_2), title_size=18,
                                show_min=False, show_max=False),
        bottom_axis=fch.ChartAxis(label_size=22, label_spacing=1, show_min=False, show_max=False),
        border=ft.Border.all(1, g.DIVIDER), interactive=False, animation=ft.Animation(0), expand=True,
    )
    legend = ft.Row([ft.Container(width=12, height=3, bgcolor=g.SERIES[field], border_radius=1),
                     ft.Text(label, size=11, color=g.TEXT_2, expand=True),
                     ft.Text("t (s)", size=11, color=g.TEXT_DISABLED)], spacing=6)
    return panel(ft.Column([legend, chart], spacing=4, expand=True), expand=True), chart


# --------------------------------------------------------------------------- the page
async def main(page: ft.Page):
    page.title = "ControlHub AA26 — Flet demo"
    page.theme_mode = ft.ThemeMode.DARK
    page.theme = ft.Theme(color_scheme_seed=g.PRIMARY)
    page.dark_theme = ft.Theme(color_scheme=ft.ColorScheme(primary=g.PRIMARY, on_primary="#0b1a22", surface=g.BG))
    page.bgcolor = g.BG
    page.padding = 0
    page.window.width, page.window.height = 1280, 800

    sim = HubSim()
    push = FpsMeter()
    gauge_rate = FpsMeter()

    # ---- header + sim controls
    scenario = ft.Dropdown(value=SCENARIOS[0], options=[ft.DropdownOption(key=s, text=s) for s in SCENARIOS],
                           on_select=lambda e: sim.set_scenario(e.control.value), dense=True, width=220, text_size=13)
    rates = ft.Text(size=11, color=g.TEXT_2, width=170)
    header = ft.Container(ft.Row([
        ft.Text(spans=[ft.TextSpan("ControlHub ", ft.TextStyle(weight=ft.FontWeight.BOLD)),
                       ft.TextSpan("AA26", ft.TextStyle(color=g.TEXT_2))], size=16),
        ft.Container(expand=True), ft.Text("Sim:", color=g.TEXT_2), scenario,
        ft.OutlinedButton("Remote button 1", on_click=lambda _: sim.remote_button(),
                          tooltip="Start / stop a run as the remote hub would"),
        rates, chip("SIM · connected", "success"),
    ], spacing=10), padding=ft.Padding.symmetric(horizontal=12, vertical=6),
        border=ft.Border.only(bottom=ft.BorderSide(1, g.DIVIDER)))
    tabs = ft.Tabs(length=5, selected_index=0, content=ft.TabBar(
        tabs=[ft.Tab(label=t) for t in ("Dashboard", "Config", "MQTT log", "Files", "Dev")],
        tab_alignment=ft.TabAlignment.START, scrollable=True, divider_color=g.DIVIDER,
        indicator_color=g.PRIMARY, label_color=g.PRIMARY, unselected_label_color=g.TEXT_2))

    # ---- DashboardControl.tsx
    mode_chip = chip("Idle")
    direction = ft.Dropdown(value="forward", options=[ft.DropdownOption("forward", "Forward"),
                                                      ft.DropdownOption("reverse", "Reverse")],
                            on_select=lambda e: sim.set_direction(e.control.value), dense=True, text_size=13,
                            expand=True)
    start = CmdButton("Start", ft.Icons.PLAY_ARROW, "start", sim.start)
    dial = CanvasGauge(0, DIAL_RPM_MAX, "Target", "RPM", g.SERIES["rpm"], dial=True, on_change=sim.set_rpm)
    dial_box = ft.Container(dial.control, height=140)
    up = CmdButton("Up", ft.Icons.ARROW_UPWARD, "up", sim.lift_up, expand=True)
    down = CmdButton("Down", ft.Icons.ARROW_DOWNWARD, "down", sim.lift_down, expand=True)
    updown = ft.Row([up.control, down.control], spacing=8)
    lift_dir = ft.Dropdown(value="forward", options=[ft.DropdownOption("forward", "Forward"),
                                                     ft.DropdownOption("reverse", "Reverse")],
                           on_select=lambda e: setattr(sim, "lift_direction", e.control.value), dense=True,
                           text_size=13, expand=True)
    move = CmdButton("Start", ft.Icons.PLAY_ARROW, "move", sim.lift_move)
    forrev = ft.Column([ft.Row([lift_dir]), move.control], spacing=8, visible=False)

    def move_mode(e):
        sim.move_mode = e.control.value
        updown.visible = sim.move_mode == "upDown"
        forrev.visible = sim.move_mode == "forRev"
        page.update()

    lift_caption = ft.Text(size=11, color=g.TEXT_2, text_align=ft.TextAlign.CENTER)
    lamp_dot = ft.Container(width=12, height=12, border_radius=6)
    lamp_text = ft.Text("Done", weight=ft.FontWeight.W_600, size=13)
    lamp = ft.Container(ft.Row([lamp_dot, lamp_text], alignment=ft.MainAxisAlignment.CENTER), border_radius=6,
                        padding=6)
    progress = ft.Text(size=11, color=g.TEXT_2, text_align=ft.TextAlign.CENTER)
    stop = CmdButton("Stop", ft.Icons.STOP, "stop", sim.stop)
    overline = lambda t: ft.Text(t, size=11, color=g.TEXT_2, style=ft.TextStyle(letter_spacing=1))
    center = lambda c: ft.Row([c], alignment=ft.MainAxisAlignment.CENTER)
    control = panel(ft.Column([
        overline("CONTROL"), ft.Row([direction]), start.control, dial_box, ft.Divider(height=1, color=g.DIVIDER),
        overline("LIFT"),
        ft.Row([ft.Dropdown(value="upDown", options=[ft.DropdownOption("upDown", "Up/Down"),
                                                    ft.DropdownOption("forRev", "For/Rev")],
                            on_select=move_mode, dense=True, text_size=13, expand=True)]),
        updown, forrev, center(lift_caption), lamp, center(progress), ft.Divider(height=1, color=g.DIVIDER),
        stop.control,
    ], spacing=8, scroll=ft.ScrollMode.AUTO), "Control", mode_chip, width=240)

    # ---- DashboardPage.tsx
    gauges = {
        "rpm": CanvasGauge(0, RPM_MAX, "Speed", "RPM", g.SERIES["rpm"], warn=RPM_MAX * 0.8, danger=RPM_MAX * 0.93),
        "duty": CanvasGauge(0, 100, "Duty", "%", g.SERIES["duty"], decimals=1, major_ticks=5),
        "current": CanvasGauge(0, CURRENT_MAX, "Current", "A", g.SERIES["current"], decimals=2,
                               warn=CURRENT_MAX * 0.7, danger=CURRENT_MAX * 0.9, major_ticks=5),
    }
    gauge_row = ft.Row([panel(ft.Container(gg.control, expand=True), t, expand=True)
                        for gg, t in zip(gauges.values(), ("Speed", "PWM duty cycle", "Current"))],
                       spacing=12, height=210)
    charts = {}
    rpm_panel, charts["rpm"] = strip_chart("rpm", "Speed (RPM)", "RPM")
    duty_panel, charts["duty"] = strip_chart("duty", "PWM duty (%)", "%", (0, 100))
    cur_panel, charts["current"] = strip_chart("current", "Current (A)", "A")
    right = ft.Column([gauge_row, rpm_panel, ft.Row([duty_panel, cur_panel], spacing=12, expand=True)],
                      spacing=12, expand=True)

    page.add(ft.Column([header, tabs, ft.Container(ft.Row([control, right], spacing=12, expand=True,
                                                          vertical_alignment=ft.CrossAxisAlignment.STRETCH),
                                                   padding=12, expand=True)], spacing=0, expand=True))
    page.on_keyboard_event = lambda e: dial.key(e.key)

    last = {}

    def refresh_controls():
        s = sim
        changed = False
        chip_state = s.mode_chip()
        if last.get("chip") != chip_state:
            last["chip"] = chip_state
            set_chip(mode_chip, *chip_state)
            changed = True
        dir_state = (s.direction, not s.start_blocked() and s.busy is None)
        if last.get("dir") != dir_state:
            last["dir"] = dir_state
            direction.value, direction.disabled = s.direction, not dir_state[1]
            changed = True
        changed |= start.refresh(s.busy, s.start_blocked())
        for b in (up, down, move):
            changed |= b.refresh(s.busy, s.lift_blocked())
        changed |= stop.refresh(s.busy, "")
        d = s.dial()
        dial.set_mode(d.value, d.state)
        if dial_box.tooltip != (d.tooltip or None):
            dial_box.tooltip = d.tooltip or None
            changed = True
        texts = (s.lift_caption(), s.lift_progress(), s.done, s.scenario)
        if last.get("texts") != texts:
            last["texts"] = texts
            lift_caption.value, progress.value = texts[0], texts[1]
            lamp.border = ft.Border.all(1, g.SUCCESS if s.done else g.DIVIDER)
            lamp_dot.bgcolor = g.SUCCESS if s.done else "#3a4049"
            lamp_dot.shadow = ft.BoxShadow(blur_radius=6, color=g.SUCCESS) if s.done else None
            lamp_text.color = g.SUCCESS if s.done else g.TEXT_DISABLED
            scenario.value = s.scenario
            changed = True
        hz = lambda m: m.text().split(" ·")[0].replace("fps", "Hz")
        rates.value = f"push: gauges {hz(gauge_rate)}, charts {hz(push)}"
        rates.update()
        if changed:
            # page.update() diffs the whole tree (charts included), so only when something changed
            page.update()

    def push_charts():
        push.frame()
        t_max = max(WINDOW_SEC, sim.now())
        for k, ch in charts.items():
            t, y = sim.history(k)
            i = int(np.searchsorted(t, t_max - WINDOW_SEC - 0.1))
            t, y = t[i:], y[i:]
            # Every point is a control Flet serialises (~0.1 ms each), so keep the count down
            if len(t) > 120:
                step = len(t) // 120 + 1
                t, y = t[::step], y[::step]
            ch.data_series[0].points = [fch.LineChartDataPoint(round(a, 3), round(b, 3)) for a, b in zip(t, y)]
            ch.min_x, ch.max_x = t_max - WINDOW_SEC, t_max
            if k != "duty" and len(y):
                lo, hi = float(y.min()), float(y.max())
                pad = max((hi - lo) * 0.1, 0.05 if k == "current" else 5)
                ch.min_y, ch.max_y = max(0.0, lo - pad), hi + pad
            ch.update()

    async def loop():
        n = 0
        period = 1 / 30
        due = asyncio.get_running_loop().time()
        while True:
            sim.step()
            gauge_rate.frame()
            for k, gg in gauges.items():
                gg.set_value(sim.latest(k))
            n += 1
            if n % 3 == 0:
                push_charts()
                refresh_controls()
            # To a deadline, not a fixed sleep (that would add the work's time to every period)
            due += period
            now = asyncio.get_running_loop().time()
            if due < now:
                due = now
            await asyncio.sleep(due - now)

    page.run_task(loop)


if __name__ == "__main__":
    ft.run(main)
