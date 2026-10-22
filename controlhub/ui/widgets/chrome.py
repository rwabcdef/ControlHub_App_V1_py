"""Panel chrome and small controls shared by the pages: the Electron app's Panel, MUI's
Chip / Alert / TextField / loading Button, and the Done / Ping lamps."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

from .. import theme


def label(text: str = "", name: str | None = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


def divider() -> QFrame:
    d = QFrame()
    d.setObjectName("divider")
    return d


def button(text: str, on_click: Callable[[], None] | None = None, variant: str = "contained",
           tone: str | None = None) -> QPushButton:
    b = QPushButton(text)
    b.setProperty("variant", variant)
    if tone:
        b.setProperty("tone", tone)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click is not None:
        b.clicked.connect(lambda: on_click())
    return b


class Panel(QFrame):
    """Titled card whose body stretches to fill the panel (components/Panel.tsx).
    `body` is the layout to add content to; `action` sits at the right of the title row."""

    def __init__(self, title: str | QWidget | None = None, action: QWidget | None = None,
                 margins: int = 12) -> None:
        super().__init__()
        self.setObjectName("panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(margins, margins - 2, margins, margins)
        outer.setSpacing(8)
        self.title_label: QLabel | None = None
        if title is not None or action is not None:
            row = QHBoxLayout()
            row.setSpacing(8)
            if isinstance(title, QWidget):
                row.addWidget(title, 1)
            else:
                self.title_label = label(title or "", "panelTitle")
                row.addWidget(self.title_label, 1)
            if action is not None:
                row.addWidget(action)
            outer.addLayout(row)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        self.body.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(self.body, 1)

    def set_title(self, text: str) -> None:
        if self.title_label is not None:
            self.title_label.setText(text)


class Chip(QLabel):
    """MUI Chip, small: role 'default' (outlined), 'success', 'info', 'warning', 'error'."""

    TONES = {"success": theme.SUCCESS, "info": theme.INFO, "warning": theme.WARNING, "error": theme.ERROR}

    def __init__(self, text: str = "", role: str = "default", outlined: bool | None = None) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(22)  # Qt drops the rounding if the radius exceeds half the height
        self._state: tuple | None = None
        self.set(text, role, outlined)

    def set(self, text: str, role: str = "default", outlined: bool | None = None) -> None:
        outlined = role == "default" if outlined is None else outlined
        if (text, role, outlined) == self._state:
            return
        self._state = (text, role, outlined)
        tone = self.TONES.get(role, theme.DIVIDER)
        fg = (theme.TEXT_2 if role == "default" else tone) if outlined else "#0b1a12"
        bg = "transparent" if outlined else tone
        self.setText(text)
        self.setStyleSheet(f"QLabel {{ color: {fg}; background: {bg}; border: 1px solid {tone}; border-radius: 11px;"
                           f" padding: 1px 9px; font-size: 12px; }}")


class Spinner(QWidget):
    """MUI CircularProgress, small: a rotating arc."""

    def __init__(self, size: int = 14, color: str = theme.PRIMARY) -> None:
        super().__init__()
        self._color = QColor(color)
        self._angle = 0
        self.setFixedSize(size, size)
        self._timer = QTimer(self, interval=30, timeout=self._step)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def showEvent(self, e) -> None:  # noqa: N802
        self._timer.start()
        super().showEvent(e)

    def hideEvent(self, e) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(e)

    def _step(self) -> None:
        self._angle = (self._angle + 12) % 360
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = max(1.5, self.width() / 8)
        p.setPen(QPen(self._color, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        r = QRectF(w, w, self.width() - 2 * w, self.height() - 2 * w)
        p.drawArc(r, int(-self._angle * 16), int(-270 * 16))


class Lamp(QFrame):
    """Lamp + label in an outlined box: grey when off, a spinner while busy, else lit in
    `tone` with a glow. The Dashboard's Done indicator and the Ping lift result."""

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self.setObjectName("lamp")
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 5, 8, 5)
        row.setSpacing(8)
        row.addStretch()
        self._dot = QLabel()
        self._dot.setFixedSize(12, 12)
        self._spinner = Spinner(12, theme.INFO)
        self._spinner.hide()
        self._text = QLabel(text)
        row.addWidget(self._dot)
        row.addWidget(self._spinner)
        row.addWidget(self._text)
        row.addStretch()
        self._state: tuple | None = None
        self.set(text, None)

    def set(self, text: str, tone: str | None, busy: bool = False) -> None:
        """tone: a colour to light it in, or None for off (grey)."""
        if (text, tone, busy) == self._state:
            return
        self._state = (text, tone, busy)
        color = theme.INFO if busy else tone or theme.TEXT_DISABLED
        border = tone or theme.DIVIDER
        self.setStyleSheet(f"QFrame#lamp {{ background: transparent; border: 1px solid {border}; border-radius: 6px; }}")
        self._text.setText(text)
        self._text.setStyleSheet(f"color: {color}; font-weight: 600; background: transparent;")
        self._dot.setVisible(not busy)
        self._spinner.setVisible(busy)
        glow = f"border: 3px solid {QColor(tone).darker(180).name()};" if tone else ""
        self._dot.setStyleSheet(f"background: {tone or '#3a4049'}; border-radius: 6px; {glow}")


class CmdButton(QWidget):
    """A contained button that shows a spinner while its command is in flight (MUI's
    loading Button), and whose tooltip says why it's disabled, if it is."""

    clicked = Signal()

    def __init__(self, text: str, glyph: str = "", variant: str = "contained", tone: str | None = None) -> None:
        super().__init__()
        self._text = f"{glyph}  {text}" if glyph else text
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.button = button(self._text, self.clicked.emit, variant, tone)
        self.button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.button.setMinimumHeight(32)
        lay.addWidget(self.button)
        self._spinner = Spinner(16, theme.TEXT_DISABLED)
        self._spinner.setParent(self.button)
        self._spinner.hide()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_state(self, reason: str = "", loading: bool = False, busy_elsewhere: bool = False) -> None:
        """reason: why it's disabled ('' = enabled). loading: its command is in flight.
        busy_elsewhere: another command is in flight (disabled, no reason shown)."""
        self.button.setEnabled(not reason and not busy_elsewhere and not loading)
        self.button.setText("" if loading else self._text)
        self._spinner.setVisible(loading)
        self._center_spinner()
        if self.button.toolTip() != reason:
            self.button.setToolTip(reason)

    def _center_spinner(self) -> None:
        self._spinner.move((self.button.width() - 16) // 2, (self.button.height() - 16) // 2)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._center_spinner()


class Alert(QFrame):
    """MUI outlined Alert: severity 'error' | 'warning' | 'success' | 'info', optional
    action button and close (x). Hidden until show_message()."""

    TONES = {"error": (theme.ERROR, theme.ERROR_TEXT), "warning": (theme.WARNING, "#ffb74d"),
             "success": (theme.SUCCESS, "#81c784"), "info": (theme.INFO, "#4fc3f7")}

    def __init__(self, closable: bool = True) -> None:
        super().__init__()
        self.setObjectName("alert")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 6, 6)
        row.setSpacing(8)
        self._icon = QLabel()
        self._text = QLabel()
        self._text.setWordWrap(True)
        self._text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._action = button("", None, "text")
        self._action.hide()
        self._action_cb: Callable[[], None] | None = None
        self._action.clicked.connect(lambda: self._action_cb and self._action_cb())
        row.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self._text, 1)
        row.addWidget(self._action, 0, Qt.AlignmentFlag.AlignTop)
        if closable:
            x = QToolButton()
            x.setText("✕")
            x.setCursor(Qt.CursorShape.PointingHandCursor)
            x.clicked.connect(self.hide)
            row.addWidget(x, 0, Qt.AlignmentFlag.AlignTop)
        self.hide()

    def show_message(self, text: str, severity: str = "error", action: tuple[str, Callable[[], None]] | None = None) -> None:
        border, fg = self.TONES[severity]
        glyph = {"error": "⊗", "warning": "⚠", "success": "✓", "info": "ⓘ"}[severity]
        self.setStyleSheet(f"QFrame#alert {{ background: transparent; border: 1px solid {border}; border-radius: 4px; }}"
                           f"QFrame#alert QLabel {{ color: {fg}; background: transparent; }}")
        self._icon.setText(glyph)
        self._text.setText(text)
        if action:
            self._action.setText(action[0])
            self._action_cb = action[1]
            self._action.show()
        else:
            self._action.hide()
        self.show()


class Field(QWidget):
    """MUI TextField, small: label above, line edit, helper text below (red when invalid)."""

    edited = Signal(str)
    committed = Signal()
    """Enter pressed or focus left the box"""

    def __init__(self, label_text: str, helper: str = "", placeholder: str = "", password: bool = False) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        self._label = label(label_text, "caption")
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        if password:
            self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._helper = label(helper, "helper", wrap=True)
        self._helper.setVisible(bool(helper))
        self._helper_text = helper
        lay.addWidget(self._label)
        lay.addWidget(self.edit)
        lay.addWidget(self._helper)
        self.edit.textEdited.connect(self.edited.emit)
        self.edit.returnPressed.connect(self.committed.emit)
        self.edit.editingFinished.connect(self._finished)
        self._invalid = False

    def _finished(self) -> None:
        if not self.edit.hasFocus():  # left the box (returnPressed covers Enter)
            self.committed.emit()

    def text(self) -> str:
        return self.edit.text()

    def set_text(self, text: str) -> None:
        if self.edit.text() != text:
            self.edit.setText(text)

    def set_helper(self, text: str, error: bool = False) -> None:
        self._helper.setText(text)
        self._helper.setVisible(bool(text))
        self._helper.setObjectName("helperError" if error else "helper")
        theme.restyle(self._helper)

    def set_invalid(self, invalid: bool, error_helper: str | None = None) -> None:
        """Red outline, and the helper swapped for `error_helper` while invalid."""
        if invalid != self._invalid:
            self._invalid = invalid
            self.edit.setProperty("invalid", invalid)
            theme.restyle(self.edit)
        self.set_helper(error_helper if invalid and error_helper else self._helper_text, invalid and bool(error_helper))

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        self.edit.setEnabled(enabled)
