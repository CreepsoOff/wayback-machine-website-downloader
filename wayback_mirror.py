#!/usr/bin/env python3
"""Backward-compatible source-checkout entry point."""

from __future__ import annotations

import pathlib
import sys

SOURCE = pathlib.Path(__file__).resolve().parent / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from wayback_machine_downloader.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
