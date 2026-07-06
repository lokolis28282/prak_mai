#!/usr/bin/env python3
"""Точка запуска системы учета склада."""

import sys

from inventory.cli import main


if __name__ == "__main__":
    if len(sys.argv) == 1 or (len(sys.argv) > 1 and sys.argv[1] in {"gui", "web"}):
        from inventory.webapp import main as gui_main

        gui_args = sys.argv[2:] if len(sys.argv) > 1 else []
        raise SystemExit(gui_main(gui_args))
    raise SystemExit(main())
