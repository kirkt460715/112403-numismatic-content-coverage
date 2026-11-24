"""Convenience entry point: ``python3 main.py [analyze|snapshot|impact|...]``.

With no arguments it runs the current coverage analysis and writes ``reports/``.
"""

import sys

from coverage_tool.cli import main

if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.extend(["analyze"])
    raise SystemExit(main())
