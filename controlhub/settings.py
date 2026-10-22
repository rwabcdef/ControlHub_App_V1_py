"""Persisted app settings (main/settings.ts, plus the display prefs the Electron app kept
in localStorage).

One JSON file, settings.json, in %APPDATA%\\ControlHub (or ~/.config/ControlHub). The
keys are the Electron app's, so the file reads the same:
    { "comms": {...}, "allowedDirs": [...], "controlHub": {...}, "display": {...} }
CONTROLHUB_SETTINGS overrides the path (tests, a second profile).
"""
from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from .types import CommsConfig, ControlHubSettings, DisplaySettings


@dataclass
class Settings:
    comms: CommsConfig = field(default_factory=CommsConfig)
    allowed_dirs: list[str] = field(default_factory=list)
    """Directories the user has granted file access to"""
    control_hub: ControlHubSettings = field(default_factory=ControlHubSettings)
    """Config -> ControlHub settings kept by the app (the hub keeps gain, max duty and speed)"""
    display: DisplaySettings = field(default_factory=DisplaySettings)


def settings_path() -> Path:
    override = os.environ.get("CONTROLHUB_SETTINGS")
    if override:
        return Path(override)
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"])
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "ControlHub" / "settings.json"


# ---- JSON <-> dataclasses, with the TS key names
_KEYS = {"baud_rate": "baudRate", "telemetry_topic": "telemetryTopic", "command_topic": "commandTopic",
         "allowed_dirs": "allowedDirs", "control_hub": "controlHub", "lift_distance": "liftDistance",
         "dial_rpm_max": "dialRpmMax", "rpm_max": "rpmMax", "current_max": "currentMax", "window_sec": "windowSec",
         "left_panel_open": "leftPanelOpen", "dash_control_open": "dashControlOpen"}


def _to_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {_KEYS.get(k, k): _to_json(v) for k, v in obj.items()}
    return obj


def _merge(cls, default, stored: Any):
    """Stored values over the defaults, field by field; anything malformed keeps the default."""
    if not isinstance(stored, dict):
        return default
    out = {}
    for f in fields(cls):
        cur = getattr(default, f.name)
        raw = stored.get(_KEYS.get(f.name, f.name), None)
        if raw is None:
            out[f.name] = cur
        elif hasattr(cur, "__dataclass_fields__"):
            out[f.name] = _merge(type(cur), cur, raw)
        elif isinstance(cur, bool):
            out[f.name] = raw if isinstance(raw, bool) else cur
        elif isinstance(cur, (int, float)):
            ok = isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(raw)
            if isinstance(cur, int):
                out[f.name] = int(raw) if ok and float(raw).is_integer() else cur
            else:
                out[f.name] = float(raw) if ok else cur
        elif isinstance(cur, str):
            out[f.name] = raw if isinstance(raw, str) else cur
        elif isinstance(cur, list):
            out[f.name] = [x for x in raw if isinstance(x, str)] if isinstance(raw, list) else cur
        else:
            out[f.name] = cur
    return cls(**out)


class SettingsStore:
    """Read once (defaults on first run or an unreadable file); every update rewrites the file."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings_path()
        self._cache: Settings | None = None

    def get(self) -> Settings:
        if self._cache is None:
            try:
                stored = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                stored = {}  # first run or unreadable file: fall back to defaults
            self._cache = _merge(Settings, Settings(), stored)
        return self._cache

    def update(self, **patch: Any) -> Settings:
        """update(comms=..., allowed_dirs=..., control_hub=..., display=...): replace those, save, return all."""
        self._cache = replace(self.get(), **patch)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(_to_json(asdict(self._cache)), indent=2), encoding="utf-8")
        tmp.replace(self.path)
        return self._cache


settings = SettingsStore()
"""The app's settings (one per process)."""
