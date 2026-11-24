"""Compatibility-friendly module name for scripted coverage analysis."""

from coverage_tool import (
    analyze_coverage,
    analyze_repository,
    analyze_scope,
    build_markdown_report,
    compare_revisions,
    render_impact_markdown,
    render_markdown,
    run_coverage_analysis,
)

__all__ = [
    "analyze_coverage",
    "analyze_repository",
    "analyze_scope",
    "build_markdown_report",
    "compare_revisions",
    "render_impact_markdown",
    "render_markdown",
    "run_coverage_analysis",
]
