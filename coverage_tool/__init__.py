"""Content coverage analysis for the coin-culture curriculum."""

from .analyzer import analyze_coverage, analyze_repository, analyze_scope
from .impact import compare_revisions
from .io import load_repository, repository_snapshot
from .reporting import render_impact_markdown, render_markdown

__all__ = [
    "analyze_coverage",
    "analyze_repository",
    "analyze_scope",
    "compare_revisions",
    "load_repository",
    "repository_snapshot",
    "render_impact_markdown",
    "render_markdown",
    "run_coverage_analysis",
    "build_markdown_report",
]

# Friendly aliases for scripted use.
run_coverage_analysis = analyze_coverage
build_markdown_report = render_markdown
