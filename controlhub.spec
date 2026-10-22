# PyInstaller one-folder build: dist/ControlHub/ControlHub.exe (+ its _internal folder).
#     .venv\Scripts\pyinstaller controlhub.spec --noconfirm
# Copy the whole dist/ControlHub folder to install; no Python needed on the target PC.

# Qt modules the app doesn't use - leaving them out makes the build several hundred MB smaller.
EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets", "PySide6.QtQml", "PySide6.Qt3DCore",
    "PySide6.Qt3DRender", "PySide6.QtCharts", "PySide6.QtGraphs", "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSql",
    "PySide6.QtDesigner", "PySide6.QtLocation", "PySide6.QtPositioning", "PySide6.QtSensors",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtTextToSpeech", "PySide6.QtWebSockets",
    "PySide6.QtHttpServer", "PySide6.QtSpatialAudio", "PySide6.QtVirtualKeyboard",
    "tkinter", "matplotlib", "scipy", "pytest",
]

a = Analysis(
    ["run_controlhub.py"],
    pathex=["."],
    hiddenimports=["PySide6.QtSerialPort"],
    excludes=EXCLUDES,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="ControlHub",
    console=False,  # a GUI app; run `python -m controlhub --debug` from source for the SerLink trace
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="ControlHub", upx=False)
