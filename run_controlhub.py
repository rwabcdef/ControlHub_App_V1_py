"""Entry script for the PyInstaller build (it can't run `python -m controlhub` directly)."""
from controlhub.__main__ import main

if __name__ == "__main__":
    main()
