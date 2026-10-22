"""File access limited to directories the user has granted (main/fsAccess.ts).

In the Electron app this sandboxed an untrusted renderer. Here the whole app is one
trusted process, but the Files page keeps the same model - you work inside folders
you picked, and paths are relative to one of them - so every path is still resolved
(symlinks included) and refused if it escapes its root.
"""
from __future__ import annotations

import os
from pathlib import Path

from .settings import SettingsStore, settings
from .types import DirEntry

MAX_READ_BYTES = 10 * 1024 * 1024


class FsError(Exception):
    """str() is the message to show."""


def _is_inside(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


class FsAccess:
    def __init__(self, store: SettingsStore = settings) -> None:
        self._store = store

    def roots(self) -> list[str]:
        return list(self._store.get().allowed_dirs)

    def add_root(self, picked: str) -> list[str]:
        """Grant a directory (picked in a native dialog). Returns the roots."""
        dirs = self.roots()
        if picked and picked not in dirs:
            dirs = self._store.update(allowed_dirs=[*dirs, picked]).allowed_dirs
        return list(dirs)

    def remove_root(self, root: str) -> list[str]:
        return list(self._store.update(allowed_dirs=[d for d in self.roots() if d != root]).allowed_dirs)

    def resolve_in_root(self, root: str, rel: str) -> Path:
        """Resolve `rel` under `root`, following symlinks of the deepest existing ancestor."""
        if root not in self.roots():
            raise FsError(f"Directory not granted: {root}")
        real_root = Path(os.path.realpath(root))
        target = Path(os.path.normpath(real_root / (rel or ".")))
        if not _is_inside(real_root, target):
            raise FsError("Path outside granted directory")
        existing = target
        while not existing.exists():
            if existing.parent == existing:
                raise FsError(f"No such path: {rel}")
            existing = existing.parent
        if not _is_inside(real_root, Path(os.path.realpath(existing))):
            raise FsError("Path outside granted directory")
        return target

    def read_dir(self, root: str, rel: str) -> list[DirEntry]:
        d = self.resolve_in_root(root, rel)
        out = []
        try:
            names = os.listdir(d)
        except OSError as e:
            raise FsError(str(e)) from e
        for name in names:
            try:
                st = (d / name).stat()
            except OSError:
                continue  # skip entries we can't stat (broken links, permissions)
            out.append(DirEntry(name, (d / name).is_dir(), st.st_size, st.st_mtime * 1000))
        # Directories first, then by name
        return sorted(out, key=lambda e: (not e.is_dir, e.name.lower()))

    def read_text(self, root: str, rel: str) -> str:
        f = self.resolve_in_root(root, rel)
        try:
            if f.stat().st_size > MAX_READ_BYTES:
                raise FsError("File too large to open")
            # newline="": line endings as they are on disk, as Node reads them
            return f.read_text(encoding="utf-8", errors="replace", newline="")
        except OSError as e:
            raise FsError(str(e)) from e

    def write_text(self, root: str, rel: str, content: str) -> None:
        f = self.resolve_in_root(root, rel)
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(content, encoding="utf-8", newline="")  # no \n -> \r\n on Windows
        except OSError as e:
            raise FsError(str(e)) from e
