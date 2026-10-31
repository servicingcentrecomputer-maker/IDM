"""Entry point for the standalone IDM_NativeHost.exe build."""

from __future__ import annotations

from integrations.native_host import main

if __name__ == "__main__":
    raise SystemExit(main())
