"""python launch.py [--debug]

Starts the app with the project's .venv, whichever Python runs this script and whatever
the working directory. Arguments are passed through to `python -m controlhub`.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


def main() -> int:
    if not VENV_PYTHON.exists():
        print(f"No virtualenv at {VENV_PYTHON.parent.parent} - create it and install the app first.",
              file=sys.stderr)
        return 1
    return subprocess.call([str(VENV_PYTHON), "-m", "controlhub", *sys.argv[1:]], cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
