"""python -m controlhub [--debug]

--debug traces every SerLink frame to the console (SERLINK_DEBUG=1 does the same) -
the Electron app's dev-build SerLink trace.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="controlhub", description="ControlHub AA26 desktop app")
    parser.add_argument("--debug", action="store_true", help="trace SerLink frames to the console")
    args, qt_args = parser.parse_known_args()
    if args.debug:
        os.environ["SERLINK_DEBUG"] = "1"  # read when comms.hub is imported
    logging.basicConfig(level=logging.INFO if os.environ.get("SERLINK_DEBUG") else logging.WARNING,
                        format="[%(name)s] %(message)s")

    import qasync
    from PySide6.QtWidgets import QApplication

    from .context import build_context
    from .ui.main_window import MainWindow
    from .ui.theme import STYLESHEET

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("ControlHub")
    app.setStyleSheet(STYLESHEET)
    # The app ends when run() returns, not when Qt sees the last window close: a Qt quit
    # stops qasync's loop before pending coroutines can finish, and asyncio's cleanup
    # after that crashes.
    app.setQuitOnLastWindowClosed(False)

    async def run() -> None:
        win = MainWindow(build_context())
        win.show()
        # Closing the window disconnects and finishes background work first (MainWindow.closeEvent).
        await win.finished.wait()
        # Delete the window (and the context, its children) while the event loop still runs.
        win.deleteLater()
        await asyncio.sleep(0.1)

    qasync.run(run())
    # Delete the QApplication and every widget now, in Qt's order, rather than leave them
    # to Python's garbage collector at interpreter exit (an intermittent crash on Windows).
    app.shutdown()


if __name__ == "__main__":
    main()
