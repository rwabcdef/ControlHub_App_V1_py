"""Files (pages/FilesPage.tsx): work inside directories you have granted - browse, open
and edit text files, and export the telemetry buffer as CSV. Paths are always relative
to a granted root, and fs_access refuses anything that escapes it."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import PurePath

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QListWidget, QListWidgetItem, QPlainTextEdit, QToolButton,
                               QVBoxLayout, QWidget)

from ...context import Context
from ...fs_access import FsAccess, FsError
from ...types import DirEntry
from ..widgets.chrome import Alert, Panel, button, label


def _join(a: str, b: str) -> str:
    return f"{a}/{b}" if a else b


def _base(path: str) -> str:
    return PurePath(path).name or path


class FilesPage(QWidget):
    def __init__(self, ctx: Context) -> None:
        super().__init__()
        self.ctx = ctx
        self.fs = FsAccess()
        self.root: str | None = None
        self.dir = ""
        self.entries: list[DirEntry] = []
        self.file_rel: str | None = None

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        # ---- granted directories
        add = QToolButton()
        add.setText("＋")
        add.setToolTip("Grant access to a directory")
        add.clicked.connect(self._add_root)
        roots = Panel("Granted directories", add)
        self.no_roots = label("No directories granted yet.", "caption")
        self.roots = QListWidget()
        self.roots.currentRowChanged.connect(self._on_root_row)
        roots.body.addWidget(self.no_roots)
        roots.body.addWidget(self.roots, 1)
        row.addWidget(roots, 3)

        # ---- directory
        self.crumbs = QWidget()
        self.crumbs_row = QHBoxLayout(self.crumbs)
        self.crumbs_row.setContentsMargins(0, 0, 0, 0)
        self.crumbs_row.setSpacing(0)
        self.export_btn = button("⤓  Export CSV", self._export_csv, "text")
        browser = Panel(self.crumbs, self.export_btn)
        self.listing = QListWidget()
        self.listing.itemActivated.connect(self._open)
        self.listing.itemClicked.connect(self._open)
        browser.body.addWidget(self.listing, 1)
        row.addWidget(browser, 4)

        # ---- file
        self.save_btn = button("💾  Save", self._save, "text")
        self.editor_panel = Panel("No file open", self.save_btn)
        self.msg = Alert()
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("mono")
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.hide()
        self.editor_panel.body.addWidget(self.msg)
        self.editor_panel.body.addWidget(self.editor, 1)
        row.addWidget(self.editor_panel, 5)

        self._load_roots(select_first=True)

    # ---- roots
    def _fail(self, e: BaseException) -> None:
        self.msg.show_message(str(e), "error")

    def _load_roots(self, select_first: bool = False) -> None:
        roots = self.fs.roots()
        self.roots.blockSignals(True)
        self.roots.clear()
        for r in roots:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, r)
            item.setToolTip(r)
            w = QWidget()
            wl = QHBoxLayout(w)
            wl.setContentsMargins(4, 2, 2, 2)
            text = QVBoxLayout()
            text.setSpacing(0)
            text.addWidget(label(_base(r)))
            path = label(r, "caption")
            path.setMaximumWidth(220)
            text.addWidget(path)
            wl.addLayout(text, 1)
            revoke = QToolButton()
            revoke.setText("⊘")
            revoke.setToolTip("Revoke")
            revoke.clicked.connect(lambda _c=False, root=r: self._remove_root(root))
            wl.addWidget(revoke)
            item.setSizeHint(w.sizeHint())
            self.roots.addItem(item)
            self.roots.setItemWidget(item, w)
        self.roots.blockSignals(False)
        self.no_roots.setVisible(not roots)
        if select_first or self.root not in roots:
            self._select_root(roots[0] if roots else None)
        else:  # the same root stays open, where it was
            self._mark_root()

    def _mark_root(self) -> None:
        roots = self.fs.roots()
        self.roots.blockSignals(True)
        self.roots.setCurrentRow(roots.index(self.root) if self.root in roots else -1)
        self.roots.blockSignals(False)

    def _select_root(self, root: str | None) -> None:
        self.root = root
        self.dir = ""
        self._set_file(None)
        self._mark_root()
        self._refresh()

    def _set_file(self, rel: str | None, content: str = "") -> None:
        self.file_rel = rel
        self.editor.setVisible(rel is not None)
        if rel is not None:
            self.editor.setPlainText(content)
        self.editor_panel.set_title(rel or "No file open")
        self.save_btn.setEnabled(rel is not None)

    def _on_root_row(self, i: int) -> None:
        roots = self.fs.roots()
        if 0 <= i < len(roots) and roots[i] != self.root:
            self._select_root(roots[i])

    def _add_root(self) -> None:
        picked = QFileDialog.getExistingDirectory(self, "Grant access to a directory")
        if not picked:
            return
        had_root = self.root is not None
        try:
            self.fs.add_root(str(PurePath(picked)))
        except OSError as e:
            self._fail(e)
            return
        self._load_roots(select_first=not had_root)

    def _remove_root(self, root: str) -> None:
        try:
            self.fs.remove_root(root)
        except OSError as e:
            self._fail(e)
            return
        self._load_roots(select_first=root == self.root)

    # ---- directory
    def _refresh(self) -> None:
        self.export_btn.setEnabled(self.root is not None)
        self._render_crumbs()
        self.listing.clear()
        if self.root is None:
            self.entries = []
            return
        try:
            self.entries = self.fs.read_dir(self.root, self.dir)
        except FsError as e:
            self.entries = []
            self._fail(e)
        for e in self.entries:
            text = f"📁  {e.name}" if e.is_dir else f"📄  {e.name}    ({e.size / 1024:.1f} KB)"
            item = QListWidgetItem(text)
            self.listing.addItem(item)
            if not e.is_dir and self.file_rel == _join(self.dir, e.name):
                item.setSelected(True)

    def _render_crumbs(self) -> None:
        while self.crumbs_row.count():
            w = self.crumbs_row.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        parts = self.dir.split("/") if self.dir else []
        links = [(_base(self.root) if self.root else "—", "")] + \
            [(c, "/".join(parts[: i + 1])) for i, c in enumerate(parts)]
        for n, (text, rel) in enumerate(links):
            if n:
                self.crumbs_row.addWidget(label(" / ", "caption"))
            b = button(text, lambda r=rel: self._go(r), "text")
            b.setStyleSheet("padding: 2px 4px; font-weight: 400;")
            self.crumbs_row.addWidget(b)
        self.crumbs_row.addStretch()

    def _go(self, rel: str) -> None:
        self.dir = rel
        self._refresh()

    def _open(self, item: QListWidgetItem) -> None:
        if self.root is None:
            return
        e = self.entries[self.listing.row(item)]
        rel = _join(self.dir, e.name)
        if e.is_dir:
            self._go(rel)
            return
        try:
            content = self.fs.read_text(self.root, rel)
        except FsError as err:
            self._fail(err)
            return
        self._set_file(rel, content)

    def _save(self) -> None:
        if self.root is None or self.file_rel is None:
            return
        try:
            self.fs.write_text(self.root, self.file_rel, self.editor.toPlainText())
        except FsError as e:
            self._fail(e)
            return
        self.msg.show_message(f"Saved {self.file_rel}", "success")

    def _export_csv(self) -> None:
        if self.root is None:
            return
        tel = self.ctx.telemetry
        t, rpm, duty, cur = tel.t, tel.series("rpm"), tel.series("duty"), tel.series("current")

        def fmt(v: float, d: int) -> str:
            return "" if math.isnan(v) else f"{v:.{d}f}"

        lines = ["t_s,rpm,duty_pct,current_a"]
        lines += [f"{t[i]:.4f},{fmt(rpm[i], 1)},{fmt(duty[i], 2)},{fmt(cur[i], 4)}" for i in range(len(t))]
        stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        rel = _join(self.dir, f"telemetry-{stamp.replace(':', '-').replace('.', '-')}.csv")
        try:
            self.fs.write_text(self.root, rel, "\n".join(lines))
        except FsError as e:
            self._fail(e)
            return
        self.msg.show_message(f"Exported {len(lines) - 1} samples to {rel}", "success")
        self._refresh()

