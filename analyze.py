"""Convenience entry point: ``python3 analyze.py analyze``.

The implementation lives in the dependency-free ``coverage_tool`` package.
This module also re-exports the most likely analysis functions for scripts.
"""

from coverage_tool.analyzer import analyze_coverage, analyze_repository, analyze_scope
from coverage_tool.cli import main
from coverage_tool.impact import compare_revisions
from coverage_tool.reporting import render_impact_markdown, render_markdown

__all__ = [
    "analyze_coverage",
    "analyze_repository",
    "analyze_scope",
    "compare_revisions",
    "render_markdown",
    "render_impact_markdown",
    "main",
]


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 1:
        sys.argv.extend(["analyze"])
    raise SystemExit(main())
