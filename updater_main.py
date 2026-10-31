"""Entry point for the standalone IDM_Updater.exe build."""

from __future__ import annotations

from idm.updater.updater import main

if __name__ == "__main__":
    raise SystemExit(main())
