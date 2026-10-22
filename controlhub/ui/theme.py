"""Colours and the app stylesheet - the Electron app's dark MUI theme (theme.ts).

Widgets pick a look with dynamic properties, set before the widget is shown:
    QPushButton  variant = "contained" (default) | "outlined" | "text";  tone = "warning" | "error"
    QLineEdit    invalid = True   (red outline, like an MUI TextField with error)
    QLabel       objectName = "caption" | "overline" | "panelTitle" | "helper" | "helperError" | "mono"
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

BG = "#0e1116"
PAPER = "#161b22"
DIVIDER = "#30363d"
TEXT = "#e6edf3"
TEXT_2 = "#9aa4af"
TEXT_DISABLED = "#5c6570"
TRACK = "#262c35"
DISABLED_INK = "#4a525c"
PRIMARY = "#4fc3f7"
PRIMARY_HOVER = "#81d4fa"
ON_PRIMARY = "#0b1a22"
SUCCESS = "#66bb6a"
INFO = "#29b6f6"
WARNING = "#ffa726"
ERROR = "#f44336"
ERROR_TEXT = "#f88078"
GRID = "#232a33"

SERIES = {"rpm": "#4fc3f7", "duty": "#ffb74d", "current": "#e57373"}
"""Series colours used consistently by gauges and charts (theme.ts SERIES_COLORS)"""

FONT = '"Segoe UI", "Ubuntu", "Helvetica Neue", Arial, sans-serif'
MONO = '"Cascadia Mono", Consolas, "DejaVu Sans Mono", monospace'

STYLESHEET = f"""
* {{ font-family: {FONT}; font-size: 13px; }}
QWidget {{ background: {BG}; color: {TEXT}; }}
QWidget:disabled {{ color: {TEXT_DISABLED}; }}

QFrame#panel {{ background: {PAPER}; border: 1px solid {DIVIDER}; border-radius: 6px; }}
QFrame#panel .QWidget, QFrame#panel QLabel, QFrame#panel QCheckBox, QFrame#panel QRadioButton,
QFrame#panel QStackedWidget, QFrame#panel QScrollArea {{ background: transparent; }}
QFrame#divider {{ background: {DIVIDER}; border: none; max-height: 1px; min-height: 1px; }}
QLabel#panelTitle {{ color: {TEXT_2}; font-weight: 600; }}
QLabel#overline {{ color: {TEXT_2}; font-size: 11px; letter-spacing: 1px; }}
QLabel#caption {{ color: {TEXT_2}; font-size: 11px; }}
QLabel#helper {{ color: {TEXT_2}; font-size: 11px; padding-left: 2px; }}
QLabel#helperError {{ color: {ERROR_TEXT}; font-size: 11px; padding-left: 2px; }}
QLabel#errorText {{ color: {ERROR_TEXT}; font-size: 11px; }}
QLabel#mono, QPlainTextEdit#mono {{ font-family: {MONO}; font-size: 12px; }}

QPushButton {{ background: {PRIMARY}; color: {ON_PRIMARY}; border: 1px solid {PRIMARY}; border-radius: 4px;
  padding: 5px 12px; font-weight: 600; }}
QPushButton:hover {{ background: {PRIMARY_HOVER}; border-color: {PRIMARY_HOVER}; }}
QPushButton:disabled {{ background: #2a3038; border-color: #2a3038; color: {TEXT_DISABLED}; }}
QPushButton[variant="outlined"] {{ background: transparent; color: {PRIMARY}; border: 1px solid #2f5d73; }}
QPushButton[variant="outlined"]:hover {{ background: #14262f; border-color: {PRIMARY}; }}
QPushButton[variant="outlined"][tone="warning"] {{ color: {WARNING}; border-color: #7a5520; }}
QPushButton[variant="outlined"][tone="warning"]:hover {{ background: #2a1f10; border-color: {WARNING}; }}
QPushButton[variant="outlined"]:disabled, QPushButton[variant="text"]:disabled {{
  background: transparent; color: {TEXT_DISABLED}; border-color: {DIVIDER}; }}
QPushButton[variant="outlined"]:checked {{ background: {PRIMARY}; color: {ON_PRIMARY}; border-color: {PRIMARY}; }}
QPushButton[variant="text"] {{ background: transparent; color: {PRIMARY}; border: none; padding: 4px 8px; }}
QPushButton[variant="text"]:hover {{ background: #14262f; }}
QPushButton[variant="text"]:disabled {{ border: none; }}
QToolButton {{ background: transparent; border: none; border-radius: 4px; padding: 4px; color: {TEXT_2}; }}
QToolButton:hover {{ background: #1d232b; }}
QToolButton:checked {{ color: {PRIMARY}; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{ background: transparent; border: 1px solid #3d444d;
  border-radius: 4px; padding: 5px 8px; selection-background-color: #1f3a48; }}
QLineEdit:hover, QComboBox:hover, QPlainTextEdit:hover {{ border-color: {TEXT_2}; }}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border: 1px solid {PRIMARY}; }}
QLineEdit[invalid="true"] {{ border: 1px solid {ERROR}; }}
QLineEdit:disabled, QComboBox:disabled {{ border-color: {DIVIDER}; color: {TEXT_DISABLED}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {PAPER}; border: 1px solid {DIVIDER}; selection-background-color: #1f3a48;
  outline: none; }}

QCheckBox, QRadioButton {{ spacing: 7px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; border: 2px solid {TEXT_2};
  background: transparent; }}
QCheckBox::indicator {{ border-radius: 3px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:checked {{ background: {PRIMARY}; border-color: {PRIMARY}; }}
QRadioButton::indicator:checked {{ background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
  stop:0 {PRIMARY}, stop:0.45 {PRIMARY}, stop:0.55 transparent); border-color: {PRIMARY}; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {PRIMARY}; }}

QSlider::groove:horizontal {{ height: 4px; background: {TRACK}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {PRIMARY}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {PRIMARY}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}

QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: transparent; color: {TEXT_2}; padding: 9px 14px; border: none;
  border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:selected {{ color: {PRIMARY}; border-bottom: 2px solid {PRIMARY}; }}

QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ padding: 5px 6px; border-radius: 4px; }}
QListWidget::item:hover {{ background: #1d232b; }}
QListWidget::item:selected {{ background: #1f3a48; color: {TEXT}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #3a414a; border-radius: 4px; min-height: 24px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #3a414a; border-radius: 4px; min-width: 24px; margin: 2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolTip {{ background: #2b313a; color: {TEXT}; border: none; padding: 4px 6px; font-size: 12px; }}
QSplitter::handle {{ background: {DIVIDER}; }}
"""


def restyle(w: QWidget) -> None:
    """Re-apply the stylesheet after changing a dynamic property (e.g. invalid)."""
    w.style().unpolish(w)
    w.style().polish(w)
