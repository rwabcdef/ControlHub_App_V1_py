"""settings.json (defaults, merging, the Electron app's key names) and the Files page's
granted-directory rules (no escaping a root, symlinks included)."""
import json
import os

import pytest

from controlhub.fs_access import FsAccess, FsError
from controlhub.settings import SettingsStore
from controlhub.types import ControlHubSettings


def test_defaults_on_first_run(tmp_path):
    s = SettingsStore(tmp_path / "settings.json").get()
    assert s.comms.kind == "mqtt" and s.comms.mqtt.url == "mqtt://192.168.0.196:1883"
    assert s.comms.mqtt.telemetry_topic == "hub/aa26/serlink/up" and s.comms.serial.baud_rate == 115200
    assert (s.control_hub.lift_distance, s.control_hub.dial_rpm_max) == (100, 300)
    assert s.control_hub.set_hub_time_on_launch is True
    assert s.display.window_sec == 10 and s.allowed_dirs == []


def test_merges_stored_values_and_keeps_ts_key_names(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"comms": {"kind": "serial", "serial": {"path": "COM5"}, "mqtt": {"url": 7}},
                                "controlHub": {"liftDistance": 250, "dialRpmMax": "x", "setHubTimeOnLaunch": 1},
                                "allowedDirs": ["C:/a", 3]}))
    store = SettingsStore(path)
    s = store.get()
    assert s.comms.kind == "serial" and s.comms.serial.path == "COM5" and s.comms.serial.baud_rate == 115200
    assert s.comms.mqtt.url == "mqtt://192.168.0.196:1883"  # malformed: default kept
    assert s.control_hub.lift_distance == 250 and s.control_hub.dial_rpm_max == 300
    assert s.control_hub.set_hub_time_on_launch is True  # not a bool: default kept
    assert s.allowed_dirs == ["C:/a"]
    store.update(control_hub=ControlHubSettings(lift_distance=40, dial_rpm_max=500, set_hub_time_on_launch=False))
    saved = json.loads(path.read_text())
    assert saved["controlHub"] == {"liftDistance": 40, "dialRpmMax": 500, "setHubTimeOnLaunch": False}
    assert saved["comms"]["serial"] == {"path": "COM5", "baudRate": 115200}
    assert SettingsStore(path).get().control_hub.dial_rpm_max == 500


def test_unreadable_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    assert SettingsStore(path).get().comms.kind == "mqtt"


@pytest.fixture
def fs(tmp_path):
    root = tmp_path / "granted"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "a.txt").write_text("hello\r\nworld\n", newline="")
    (tmp_path / "secret.txt").write_text("no")
    access = FsAccess(SettingsStore(tmp_path / "settings.json"))
    access.add_root(str(root))
    return access, str(root), tmp_path


def test_read_write_and_listing(fs):
    access, root, _ = fs
    assert [(e.name, e.is_dir) for e in access.read_dir(root, "")] == [("sub", True)]
    assert access.read_text(root, "sub/a.txt") == "hello\r\nworld\n"  # line endings as on disk
    access.write_text(root, "new/dir/b.csv", "x,y\n1,2")
    assert (access.resolve_in_root(root, "new/dir/b.csv")).read_bytes() == b"x,y\n1,2"


def test_cannot_escape_a_root(fs):
    access, root, tmp = fs
    for rel in ("../secret.txt", "sub/../../secret.txt", str(tmp / "secret.txt")):
        with pytest.raises(FsError, match="outside"):
            access.read_text(root, rel)
    with pytest.raises(FsError, match="not granted"):
        access.read_dir(str(tmp), "")
    access.remove_root(root)
    with pytest.raises(FsError, match="not granted"):
        access.read_dir(root, "")


def test_symlink_out_of_root_refused(fs):
    access, root, tmp = fs
    link = os.path.join(root, "escape")
    try:
        os.symlink(str(tmp), link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need Developer Mode / admin on Windows")
    with pytest.raises(FsError, match="outside"):
        access.read_text(root, "escape/secret.txt")
