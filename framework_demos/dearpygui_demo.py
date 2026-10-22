"""Candidate 5: Dear PyGui 2 (immediate-mode, GPU, Dear ImGui + ImPlot underneath).
Gauges and the dial are drawn on drawlists (re-drawn every frame - that is the
immediate-mode way, and cheap here); the strip charts are ImPlot line series.

Layout is in pixels: there are no layout managers, so sizes are recomputed
when the window resizes. Dear PyGui is not DPI-aware either: the process opts in
below and every pixel size goes through px(), or Windows bitmap-stretches the
whole window (blurry) at 125 / 150 % scaling.

Run:  .venv\\Scripts\\python dearpygui_demo.py
"""
from __future__ import annotations

import ctypes
import os

import dearpygui.dearpygui as dpg
import numpy as np

from common import geometry as g
from common.sim import CURRENT_MAX, DIAL_RPM_MAX, RPM_MAX, SCENARIOS, WINDOW_SEC, HubSim


def rgb(h: str, a: int = 255) -> list[int]:
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)] + [a]


sim = HubSim()
FONT_DIR = r"C:\Windows\Fonts"

try:  # per-monitor DPI aware, before any window exists
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    UI_SCALE = ctypes.windll.user32.GetDpiForSystem() / 96
except (AttributeError, OSError):
    UI_SCALE = 1.0


def px(v: float) -> int:
    """Design pixels (at 100 % scaling) -> device pixels."""
    return int(round(v * UI_SCALE))


# --------------------------------------------------------------------------- gauge / dial
class Gauge:
    """Gauge.tsx (dial=False) or SpeedDial.tsx (dial=True) on a drawlist."""

    def __init__(self, parent, lo, hi, label, unit, color, decimals=0, warn=None, danger=None, major_ticks=6,
                 dial=False):
        self.lo, self.hi, self.label, self.unit, self.color = lo, hi, label, unit, color
        self.decimals, self.warn, self.danger, self.major_ticks, self.dial = decimals, warn, danger, major_ticks, dial
        self.value: float | None = None
        self.text = "—"
        self.mode = "edit"
        self.dragging = False
        self.focused = False
        self.w, self.h = 200, 150
        self.ticks = g.ticks(lo, hi, major_ticks)
        self.dl = dpg.add_drawlist(width=self.w, height=self.h, parent=parent)

    def resize(self, w, h):
        self.w, self.h = max(40, int(w)), max(30, int(h))
        dpg.configure_item(self.dl, width=self.w, height=self.h)

    def _xy(self, vx, vy):
        s, ox, oy = g.view_scale(self.w, self.h)
        return [ox + s * vx, oy + s * vy]

    def _arc(self, r, a0, a1, color, width):
        if a1 - a0 < 0.05:
            return
        s = g.view_scale(self.w, self.h)[0]
        pts = [self._xy(x, y) for x, y in g.arc_points(r, a0, a1, 96)]
        dpg.draw_polyline(pts, color=rgb(color), thickness=width * s, parent=self.dl)

    def draw(self):
        s = g.view_scale(self.w, self.h)[0]
        dpg.delete_item(self.dl, children_only=True)
        ink = g.DISABLED_INK if self.mode == "disabled" else self.color
        f = 0.0 if self.value is None else g.frac(self.value, self.lo, self.hi)
        a = g.START + f * g.SWEEP
        self._arc(g.R + 6, g.START, g.START + g.SWEEP, g.TRACK, 6)
        self._arc(g.R + 6, g.START, a, ink, 6)
        if self.warn is not None:
            self._arc(g.R + 1, g.angle(self.warn, self.lo, self.hi),
                      g.angle(self.danger if self.danger is not None else self.hi, self.lo, self.hi), g.WARN, 2)
        if self.danger is not None:
            self._arc(g.R + 1, g.angle(self.danger, self.lo, self.hi), g.START + g.SWEEP, g.DANGER, 2)
        for t in self.ticks:
            dpg.draw_line(self._xy(t.x0, t.y0), self._xy(t.x1, t.y1), color=rgb(g.TEXT_2),
                          thickness=(1.5 if t.major else 0.75) * s, parent=self.dl)
            if t.label:
                self._text(t.lx, t.ly, t.label, 8.5 * s, g.TEXT_2)
        tail = 0 if self.dial else 10
        dpg.draw_line(self._xy(*g.polar(-tail, a)) if tail else self._xy(g.CX, g.CY), self._xy(*g.polar(g.R - 6, a)),
                      color=rgb(ink), thickness=2.5 * s, parent=self.dl)
        dpg.draw_circle(self._xy(g.CX, g.CY), 5 * s, color=rgb(ink), fill=rgb(g.PAPER), thickness=2 * s,
                        parent=self.dl)
        if self.dial:
            if self.value is not None:
                dpg.draw_circle(self._xy(*g.polar(g.R + 6, a)), 7 * s, color=rgb(ink), fill=rgb(g.PAPER),
                                thickness=2.5 * s, parent=self.dl)
            if self.focused and self.mode == "edit":
                dpg.draw_circle(self._xy(g.CX, g.CY), (g.R + 12) * s, color=rgb(g.PRIMARY, 140), thickness=1,
                                parent=self.dl)
            text = "—" if self.value is None else str(int(self.value))
        else:
            text = self.text
        self._text(g.CX, g.CY + 22, text, 22 * s, g.TEXT_DISABLED if self.mode == "disabled" else g.TEXT, bold=True)
        self._text(g.CX, g.CY + 42, f"{self.label} ({self.unit})", 9 * s, g.TEXT_2)

    def _text(self, cx, cy, text, size, color, bold=False):
        # draw_text anchors top-left; centre it with the font's measured width
        w, h = dpg.get_text_size(text, font=FONTS["bold" if bold else "normal"]) or (0, 0)
        k = size / FONTS["size_bold" if bold else "size"]
        x, y = self._xy(cx, cy)
        t = dpg.draw_text([x - w * k / 2, y - h * k / 2], text, size=size, color=rgb(color), parent=self.dl)
        dpg.bind_item_font(t, FONTS["bold" if bold else "normal"])

    # ---- dial input (called from the global mouse / key handlers)
    def mouse(self, pressed: bool, dragging: bool) -> bool:
        """Returns True if the value changed."""
        if self.mode != "edit":
            return False
        mx, my = dpg.get_mouse_pos(local=False)
        x0, y0 = dpg.get_item_rect_min(self.dl)
        p = g.point_at(mx - x0, my - y0, self.w, self.h)
        if pressed:
            self.focused = dpg.is_item_hovered(self.dl)
            self.dragging = bool(self.focused and p and p[1] >= g.GRAB_RADIUS and p[0] <= g.SWEEP)
        if (pressed or dragging) and self.dragging and p:
            return self._set(g.value_of(p[0], self.lo, self.hi))
        return False

    def _set(self, v) -> bool:
        nv = int(min(self.hi, max(self.lo, round(v))))
        if nv == self.value:
            return False
        self.value = nv
        return True

    def step(self, d) -> bool:
        if self.mode != "edit":
            return False
        cur = self.value if self.value is not None else self.lo
        if (cur > self.hi and d > 0) or (cur < self.lo and d < 0):
            return False
        return self._set(cur + d)


# --------------------------------------------------------------------------- UI
FONTS: dict = {}
gauges: dict[str, Gauge] = {}
series: dict[str, tuple[int, int, int]] = {}  # field -> (series, x axis, y axis)
buttons: dict[str, tuple[int, str, str]] = {}  # which -> (item, label, glyph)
SPIN = "|/-\\"
CONTROL_W = 210  # design pixels
GAUGE_H = 210


def setup_theme():
    with dpg.font_registry():
        FONTS["size"], FONTS["size_bold"] = px(16), px(30)
        FONTS["normal"] = dpg.add_font(os.path.join(FONT_DIR, "segoeui.ttf"), FONTS["size"])
        FONTS["bold"] = dpg.add_font(os.path.join(FONT_DIR, "seguisb.ttf"), FONTS["size_bold"])
        FONTS["small"] = dpg.add_font(os.path.join(FONT_DIR, "segoeui.ttf"), px(13))
        # (Dear PyGui 2 loads glyph ranges on demand: no add_font_range for ■ ▶ ↑ — etc.)
    dpg.bind_font(FONTS["normal"])
    with dpg.theme() as t:
        with dpg.theme_component(dpg.mvAll):
            c = dpg.add_theme_color
            c(dpg.mvThemeCol_WindowBg, rgb(g.BG))
            c(dpg.mvThemeCol_ChildBg, rgb(g.PAPER))
            c(dpg.mvThemeCol_Border, rgb(g.DIVIDER))
            c(dpg.mvThemeCol_Text, rgb(g.TEXT))
            c(dpg.mvThemeCol_TextDisabled, rgb(g.TEXT_DISABLED))
            c(dpg.mvThemeCol_FrameBg, rgb("#1d232b"))
            c(dpg.mvThemeCol_FrameBgHovered, rgb("#262d36"))
            c(dpg.mvThemeCol_PopupBg, rgb(g.PAPER))
            c(dpg.mvThemeCol_Button, rgb(g.PRIMARY))
            c(dpg.mvThemeCol_ButtonHovered, rgb("#81d4fa"))
            c(dpg.mvThemeCol_ButtonActive, rgb("#29b6f6"))
            c(dpg.mvThemeCol_Header, rgb("#1f3a48"))
            c(dpg.mvThemeCol_HeaderHovered, rgb("#28495a"))
            c(dpg.mvThemeCol_Tab, rgb(g.BG))
            c(dpg.mvThemeCol_TabActive, rgb(g.BG))
            c(dpg.mvThemeCol_TabHovered, rgb("#1d232b"))
            c(dpg.mvThemeCol_Separator, rgb(g.DIVIDER))
            v = dpg.add_theme_style
            v(dpg.mvStyleVar_ChildRounding, px(6))
            v(dpg.mvStyleVar_FrameRounding, px(4))
            v(dpg.mvStyleVar_ChildBorderSize, 1)
            v(dpg.mvStyleVar_FramePadding, px(8), px(6))
            v(dpg.mvStyleVar_WindowPadding, px(12), px(10))
            v(dpg.mvStyleVar_ItemSpacing, px(8), px(8))
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Text, rgb("#0b1a22"))
        with dpg.theme_component(dpg.mvButton, enabled_state=False):
            dpg.add_theme_color(dpg.mvThemeCol_Button, rgb("#2a3038"))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, rgb("#2a3038"))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, rgb("#2a3038"))
            dpg.add_theme_color(dpg.mvThemeCol_Text, rgb(g.TEXT_DISABLED))
        with dpg.theme_component(dpg.mvCombo, enabled_state=False):
            dpg.add_theme_color(dpg.mvThemeCol_Text, rgb(g.TEXT_DISABLED))
        with dpg.theme_component(dpg.mvPlot):
            dpg.add_theme_color(dpg.mvPlotCol_PlotBg, rgb(g.PAPER), category=dpg.mvThemeCat_Plots)
            dpg.add_theme_color(dpg.mvPlotCol_FrameBg, rgb(g.PAPER), category=dpg.mvThemeCat_Plots)
            dpg.add_theme_color(dpg.mvPlotCol_PlotBorder, rgb(g.PAPER), category=dpg.mvThemeCat_Plots)
            dpg.add_theme_color(dpg.mvPlotCol_AxisGrid, rgb("#232a33"), category=dpg.mvThemeCat_Plots)
            dpg.add_theme_color(dpg.mvPlotCol_AxisText, rgb(g.TEXT_2), category=dpg.mvThemeCat_Plots)
            dpg.add_theme_style(dpg.mvPlotStyleVar_PlotPadding, 4, 4, category=dpg.mvThemeCat_Plots)
    dpg.bind_theme(t)
    for k, col in g.SERIES.items():
        with dpg.theme(tag=f"line_{k}"):
            with dpg.theme_component(dpg.mvLineSeries):
                dpg.add_theme_color(dpg.mvPlotCol_Line, rgb(col), category=dpg.mvThemeCat_Plots)
                dpg.add_theme_style(dpg.mvPlotStyleVar_LineWeight, 1.5, category=dpg.mvThemeCat_Plots)
    with dpg.theme(tag="ghost"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, rgb(g.BG))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, rgb("#1d232b"))
            dpg.add_theme_color(dpg.mvThemeCol_Text, rgb(g.PRIMARY))
            dpg.add_theme_color(dpg.mvThemeCol_Border, rgb("#2f5d73"))
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
    for role, (fg, bg) in {"default": (g.TEXT_2, g.PAPER), "success": ("#0d1f0e", g.SUCCESS),
                           "info": ("#06222c", "#29b6f6")}.items():
        with dpg.theme(tag=f"chip_{role}"):
            with dpg.theme_component(dpg.mvButton):
                for col in (dpg.mvThemeCol_Button, dpg.mvThemeCol_ButtonHovered, dpg.mvThemeCol_ButtonActive):
                    dpg.add_theme_color(col, rgb(bg))
                dpg.add_theme_color(dpg.mvThemeCol_Text, rgb(fg))
                dpg.add_theme_color(dpg.mvThemeCol_Border, rgb(g.DIVIDER if role == "default" else bg))
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, px(11))
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, px(9), px(2))
    for on in (True, False):
        with dpg.theme(tag=f"lamp_{on}"):
            with dpg.theme_component(dpg.mvChildWindow):
                dpg.add_theme_color(dpg.mvThemeCol_Border, rgb(g.SUCCESS if on else g.DIVIDER))
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, rgb(g.PAPER))
                dpg.add_theme_color(dpg.mvThemeCol_Text, rgb(g.SUCCESS if on else g.TEXT_DISABLED))


def cmd_button(which: str, label: str, glyph: str, callback, width=-1):
    b = dpg.add_button(label=f"{glyph}  {label}".strip(), width=width if width < 0 else px(width), height=px(30),
                       callback=lambda: callback())
    with dpg.tooltip(b, tag=f"tip_{which}", show=False):
        dpg.add_text("", tag=f"tiptext_{which}")
    buttons[which] = (b, label, glyph)
    return b


def caption(tag):
    t = dpg.add_text("", tag=tag)
    dpg.bind_item_font(t, FONTS["small"])
    return t


def build():
    setup_theme()
    with dpg.window(tag="root", no_scrollbar=True):
        # ---- header + sim controls
        with dpg.group(horizontal=True, tag="header"):
            dpg.add_text("ControlHub")
            dpg.add_text("AA26", color=rgb(g.TEXT_2))
            dpg.add_spacer(tag="header_gap", width=px(200))
            dpg.add_text("Sim:", color=rgb(g.TEXT_2))
            dpg.add_combo(SCENARIOS, default_value=SCENARIOS[0], width=px(200), tag="scenario",
                          callback=lambda s, a: sim.set_scenario(a))
            b = dpg.add_button(label="Remote button 1", callback=sim.remote_button)
            dpg.bind_item_theme(b, "ghost")
            with dpg.tooltip(b):
                dpg.add_text("Start / stop a run as the remote hub would")
            dpg.add_text("", tag="fps", color=rgb(g.TEXT_2))
            c = dpg.add_button(label="SIM · connected")
            dpg.bind_item_theme(c, "chip_success")
        with dpg.tab_bar():
            for t in ("Dashboard", "Config", "MQTT log", "Files", "Dev"):
                dpg.add_tab(label=t)

        with dpg.group(horizontal=True, tag="body"):
            # ---- DashboardControl.tsx
            with dpg.child_window(width=px(CONTROL_W), tag="control", border=True):
                with dpg.group(horizontal=True):
                    dpg.add_text("Control", color=rgb(g.TEXT_2))
                    dpg.add_spacer(width=px(40))
                    dpg.add_button(label="Idle", tag="chip")
                caption_tag = dpg.add_text("CONTROL", color=rgb(g.TEXT_2))
                dpg.bind_item_font(caption_tag, FONTS["small"])
                dpg.add_combo(["Forward", "Reverse"], default_value="Forward", width=-1, tag="direction",
                              callback=lambda s, a: sim.set_direction(a.lower()))
                cmd_button("start", "Start", "", sim.start)  # no ▶: Segoe UI lacks it
                with dpg.group(tag="dial_box"):
                    gauges["dial"] = Gauge("dial_box", 0, DIAL_RPM_MAX, "Target", "RPM", g.SERIES["rpm"], dial=True)
                    gauges["dial"].resize(px(CONTROL_W - 24), px(140))
                with dpg.tooltip("dial_box", tag="dial_tip", show=False):  # a drawlist can't own a tooltip
                    dpg.add_text("", tag="dial_tiptext")
                dpg.add_separator()
                lt = dpg.add_text("LIFT", color=rgb(g.TEXT_2))
                dpg.bind_item_font(lt, FONTS["small"])

                def move_mode(_s, a):
                    sim.move_mode = "upDown" if a == "Up/Down" else "forRev"
                    dpg.configure_item("updown", show=sim.move_mode == "upDown")
                    dpg.configure_item("forrev", show=sim.move_mode == "forRev")

                dpg.add_combo(["Up/Down", "For/Rev"], default_value="Up/Down", width=-1, callback=move_mode)
                with dpg.group(horizontal=True, tag="updown"):
                    cmd_button("up", "Up", "↑", sim.lift_up, width=89)
                    cmd_button("down", "Down", "↓", sim.lift_down, width=89)
                with dpg.group(tag="forrev", show=False):
                    dpg.add_combo(["Forward", "Reverse"], default_value="Forward", width=-1,
                                  callback=lambda s, a: setattr(sim, "lift_direction", a.lower()))
                    cmd_button("move", "Start", "", sim.lift_move)
                caption("lift_caption")
                with dpg.child_window(height=px(34), border=True, tag="lamp", no_scrollbar=True):
                    with dpg.group(horizontal=True):
                        dpg.add_spacer(width=px(55))
                        dpg.add_text("●  Done", tag="lamp_text")
                caption("progress")
                dpg.add_separator()
                cmd_button("stop", "Stop", "", sim.stop)

            # ---- DashboardPage.tsx
            with dpg.group(tag="right"):
                with dpg.group(horizontal=True):
                    for field, title, kw in (
                        ("rpm", "Speed", dict(lo=0, hi=RPM_MAX, label="Speed", unit="RPM", warn=RPM_MAX * 0.8,
                                              danger=RPM_MAX * 0.93)),
                        ("duty", "PWM duty cycle", dict(lo=0, hi=100, label="Duty", unit="%", decimals=1,
                                                        major_ticks=5)),
                        ("current", "Current", dict(lo=0, hi=CURRENT_MAX, label="Current", unit="A", decimals=2,
                                                    warn=CURRENT_MAX * 0.7, danger=CURRENT_MAX * 0.9, major_ticks=5)),
                    ):
                        with dpg.child_window(tag=f"gp_{field}", height=px(GAUGE_H), border=True, no_scrollbar=True):
                            dpg.add_text(title, color=rgb(g.TEXT_2))
                            gauges[field] = Gauge(f"gp_{field}", color=g.SERIES[field], **kw)
                for field, label, yname, yr in (("rpm", "Speed (RPM)", "RPM", None), ("duty", "PWM duty (%)", "%", (0, 100)),
                                                ("current", "Current (A)", "A", None)):
                    with dpg.child_window(tag=f"cp_{field}", border=True, no_scrollbar=True, show=False):
                        with dpg.group(horizontal=True):
                            with dpg.drawlist(width=px(12), height=px(14)):  # legend swatch
                                dpg.draw_rectangle([0, px(6)], [px(12), px(9)], color=rgb(g.SERIES[field]),
                                                   fill=rgb(g.SERIES[field]))
                            caption(f"leg_{field}")
                            dpg.set_value(f"leg_{field}", label)
                        with dpg.plot(height=-1, width=-1, no_menus=True, no_box_select=True, no_mouse_pos=True,
                                      no_frame=True):
                            x = dpg.add_plot_axis(dpg.mvXAxis, label="t (s)", no_highlight=True)
                            y = dpg.add_plot_axis(dpg.mvYAxis, label=yname, no_highlight=True)
                            if yr:
                                dpg.set_axis_limits(y, *yr)
                            s = dpg.add_line_series([], [], parent=y)
                            dpg.bind_item_theme(s, f"line_{field}")
                            series[field] = (s, x, y)
                # Speed spans the width; duty and current share the row below
                dpg.move_item("cp_rpm", parent="right")
                with dpg.group(horizontal=True, parent="right", tag="chart_row"):
                    pass
                dpg.move_item("cp_duty", parent="chart_row")
                dpg.move_item("cp_current", parent="chart_row")
                for k in series:
                    dpg.configure_item(f"cp_{k}", show=True)

    with dpg.handler_registry():
        dpg.add_mouse_click_handler(button=dpg.mvMouseButton_Left, callback=lambda: on_mouse(True, False))
        dpg.add_mouse_drag_handler(button=dpg.mvMouseButton_Left, threshold=0, callback=lambda: on_mouse(False, True))
        dpg.add_mouse_release_handler(button=dpg.mvMouseButton_Left, callback=lambda: setattr(gauges["dial"], "dragging", False))
        dpg.add_mouse_wheel_handler(callback=on_wheel)
        dpg.add_key_press_handler(callback=on_key)


def on_mouse(pressed, dragging):
    if gauges["dial"].mouse(pressed, dragging):
        sim.set_rpm(gauges["dial"].value)


def on_wheel(_s, delta):
    d = gauges["dial"]
    if dpg.is_item_hovered(d.dl) and d.step(1 if delta > 0 else -1):
        sim.set_rpm(d.value)


def on_key(_s, key):
    d = gauges["dial"]
    if not d.focused:
        return
    steps = {dpg.mvKey_Up: 1, dpg.mvKey_Right: 1, dpg.mvKey_Down: -1, dpg.mvKey_Left: -1,
             dpg.mvKey_Prior: 10, dpg.mvKey_Next: -10}
    changed = False
    if key in steps:
        changed = d.step(steps[key])
    elif key == dpg.mvKey_Home and d.mode == "edit":
        changed = d._set(d.lo)
    elif key == dpg.mvKey_End and d.mode == "edit":
        changed = d._set(d.hi)
    if changed:
        sim.set_rpm(d.value)


def layout():
    """No layout managers: size everything from the viewport."""
    vw, vh = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
    dpg.configure_item("header_gap", width=max(px(10), vw - px(880)))
    body_h = vh - px(100)
    dpg.configure_item("control", height=body_h)
    rw = vw - px(CONTROL_W + 12 + 32)
    gw = (rw - px(16)) / 3
    for k in ("rpm", "duty", "current"):
        dpg.configure_item(f"gp_{k}", width=int(gw))
        gauges[k].resize(gw - px(26), px(GAUGE_H - 50))
    ch = (body_h - px(GAUGE_H + 16)) / 2
    dpg.configure_item("cp_rpm", width=int(rw), height=int(ch))
    dpg.configure_item("cp_duty", width=int((rw - px(8)) / 2), height=int(ch))
    dpg.configure_item("cp_current", width=int((rw - px(8)) / 2), height=int(ch))


def refresh_controls(spin: int):
    s = sim
    label, role = s.mode_chip()
    dpg.configure_item("chip", label=label)
    dpg.bind_item_theme("chip", f"chip_{role}")
    dpg.set_value("direction", "Forward" if s.direction == "forward" else "Reverse")
    dpg.configure_item("direction", enabled=not s.start_blocked() and s.busy is None)
    for which, reason in (("start", s.start_blocked()), ("up", s.lift_blocked()), ("down", s.lift_blocked()),
                          ("move", s.lift_blocked()), ("stop", "")):
        b, lbl, glyph = buttons[which]
        busy = s.busy == which
        dpg.configure_item(b, label=f"{SPIN[spin % 4]}  {lbl}" if busy else f"{glyph}  {lbl}",
                           enabled=not reason and (s.busy is None or busy))
        dpg.configure_item(f"tip_{which}", show=bool(reason))
        dpg.set_value(f"tiptext_{which}", reason)
    d = s.dial()
    dial = gauges["dial"]
    if not dial.dragging:
        dial.value = d.value
    if d.state != dial.mode:
        dial.dragging = False
    dial.mode = d.state
    dpg.configure_item("dial_tip", show=bool(d.tooltip))
    dpg.set_value("dial_tiptext", d.tooltip)
    dpg.set_value("lift_caption", s.lift_caption())
    dpg.set_value("progress", s.lift_progress())
    dpg.bind_item_theme("lamp", f"lamp_{s.done}")
    dpg.set_value("scenario", s.scenario)


def main():
    dpg.create_context()
    build()
    # ASCII title: the viewport title is not UTF-8 decoded ("—" shows as mojibake)
    dpg.create_viewport(title="ControlHub AA26 - Dear PyGui demo", width=px(1280), height=px(800), clear_color=rgb(g.BG))
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("root", True)
    dpg.set_viewport_resize_callback(lambda: layout())
    layout()
    frame = 0
    last_text = 0.0
    while dpg.is_dearpygui_running():
        sim.step()
        now = sim.now()
        if now - last_text > 0.1:  # readouts at 10 Hz, as Gauge.tsx
            last_text = now
            for k in ("rpm", "duty", "current"):
                v = sim.latest(k)
                gauges[k].text = "—" if v is None else f"{v:.{gauges[k].decimals}f}"
            refresh_controls(frame // 6)
            dpg.set_value("fps", f"{dpg.get_frame_rate():.0f} fps")
        for k in ("rpm", "duty", "current"):
            gauges[k].value = sim.latest(k)
        for gg in gauges.values():
            gg.draw()
        t_max = max(WINDOW_SEC, now)
        for k, (s, xa, ya) in series.items():
            t, y = sim.history(k)
            i = int(np.searchsorted(t, t_max - WINDOW_SEC - 0.1))
            dpg.set_value(s, [t[i:].tolist(), y[i:].tolist()])
            dpg.set_axis_limits(xa, t_max - WINDOW_SEC, t_max)
            if k != "duty":
                dpg.fit_axis_data(ya)
        frame += 1
        dpg.render_dearpygui_frame()
    dpg.destroy_context()


if __name__ == "__main__":
    main()
