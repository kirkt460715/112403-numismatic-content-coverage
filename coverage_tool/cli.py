"""Command line interface for coverage analysis, snapshots and impact review."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from .analyzer import analyze_coverage, load_recommendation_records
from .impact import compare_revisions
from .io import load_json, load_repository, repository_snapshot, write_json
from .recommendations import recommendation_from_findings
from .reporting import render_impact_markdown, render_markdown, write_report_files
from .validation import validate_repository

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BLUEPRINT = PROJECT_ROOT / "config" / "curriculum_blueprint.json"


def discover_recommendations(data_dir: Path) -> Optional[str]:
    candidates = [
        data_dir / "adopted_recommendations.csv",
        data_dir / "recommendations.csv",
        data_dir.parent / "state" / "adopted_recommendations.json",
        PROJECT_ROOT / "state" / "adopted_recommendations.json",
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return None


def _blueprint_arg(args: argparse.Namespace) -> Optional[str]:
    if getattr(args, "no_blueprint", False):
        return None
    path = Path(getattr(args, "blueprint", None) or DEFAULT_BLUEPRINT)
    return str(path) if path.exists() else None


def _recommendations_arg(args: argparse.Namespace, data_dir: Path) -> Optional[str]:
    explicit = getattr(args, "recommendations", None)
    if explicit:
        return explicit
    if getattr(args, "no_recommendations", False):
        return None
    return discover_recommendations(data_dir)


def command_analyze(args: argparse.Namespace) -> int:
    data_dir = Path(args.data)
    rec_path = _recommendations_arg(args, data_dir)
    result = analyze_coverage(
        str(data_dir),
        course_version=args.version,
        as_of=args.as_of or date.today().isoformat(),
        audience_age=args.audience_age,
        blueprint_path=_blueprint_arg(args),
        recommendations_path=rec_path,
    )
    result["generated_at"] = args.generated_at or date.today().isoformat()
    outputs = write_report_files(args.out, result, args.basename)
    print(f"Markdown: {outputs['markdown']}")
    print(f"JSON: {outputs['json']}")
    summary = result["summary"]
    print(
        "Summary: "
        f"version={result['scope']['course_version']} "
        f"segments={summary['segment_count']} "
        f"classes={summary['coverage_class_counts']}"
    )
    return 0


def command_snapshot(args: argparse.Namespace) -> int:
    data_dir = Path(args.data)
    rec_path = _recommendations_arg(args, data_dir)
    as_of = args.as_of or date.today().isoformat()
    result = analyze_coverage(
        str(data_dir),
        course_version=args.version,
        as_of=as_of,
        audience_age=args.audience_age,
        blueprint_path=_blueprint_arg(args),
        recommendations_path=rec_path,
    )
    result["generated_at"] = args.generated_at or date.today().isoformat()
    hashes = result.get("repository_snapshot", {}).get("file_hashes", {})
    combined = "-".join(sorted(hashes.values()))
    import hashlib

    short = hashlib.sha256(combined.encode("utf-8")).hexdigest()[:8]
    basename = args.basename or f"snapshot-{as_of}-{short}"
    outputs = write_report_files(args.out, result, basename)
    print(f"Immutable committee snapshot Markdown: {outputs['markdown']}")
    print(f"Immutable committee snapshot JSON: {outputs['json']}")
    return 0


def command_validate(args: argparse.Namespace) -> int:
    repo = load_repository(args.data)
    issues = validate_repository(repo)
    errors = [i for i in issues if i["level"] == "error"]
    warnings = [i for i in issues if i["level"] == "warning"]
    for issue in issues:
        print(f"[{issue['level'].upper()}] {issue['code']}: {issue['message']}")
    print(f"{len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors and args.strict else 0


def command_impact(args: argparse.Namespace) -> int:
    baseline = load_json(args.baseline)
    data_dir = Path(args.data)
    repo = load_repository(data_dir)
    rec_path = args.recommendations or discover_recommendations(data_dir)
    records = load_recommendation_records(rec_path) if rec_path else None
    blueprint = None
    blueprint_path = _blueprint_arg(args)
    if blueprint_path:
        from .taxonomy import load_blueprint

        blueprint = load_blueprint(blueprint_path)
    impact = compare_revisions(
        baseline,
        repo,
        as_of=args.as_of or date.today().isoformat(),
        audience_age=args.audience_age,
        recommendation_records=records,
        blueprint=blueprint,
    )
    impact["generated_at"] = args.generated_at or date.today().isoformat()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{args.basename}.json"
    md_path = out / f"{args.basename}.md"
    json_path.write_text(json.dumps(impact, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_impact_markdown(impact), encoding="utf-8")
    print(f"Impact Markdown: {md_path}")
    print(f"Impact JSON: {json_path}")
    print(f"Affected topics: {len(impact['affected_topics'])}; source changes: {len(impact['source_changes'])}")
    return 0


def command_adopt(args: argparse.Namespace) -> int:
    register_path = Path(args.register)
    if register_path.exists():
        payload = load_json(register_path)
        records: List[Dict[str, Any]] = payload.get("recommendations", payload if isinstance(payload, list) else [])
    else:
        records = []

    analysis = analyze_coverage(
        args.data,
        course_version=args.version,
        as_of=args.as_of or date.today().isoformat(),
        audience_age=args.audience_age,
        blueprint_path=_blueprint_arg(args),
    )
    ref_ids = [part.strip() for part in (args.reference_ids or "").split(",") if part.strip()]
    record = recommendation_from_findings(
        args.id,
        args.text,
        analysis,
        topic_id=args.topic or "",
        segment_id=args.segment or "",
        course_version=args.version or "",
        reference_ids=ref_ids,
        adopted_at=args.adopted_at or date.today().isoformat(),
    )
    records = [r for r in records if r.get("recommendation_id") != args.id]
    records.append(record)
    write_json(register_path, {"format": "coverage-tool-adopted-recommendations", "recommendations": records})
    print(f"Saved adopted recommendation {args.id} to {register_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyse coin-culture curriculum coverage and revision impact.")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data", default="data", help="Data directory containing manifest.json and CSVs")

    def add_common(p: argparse.ArgumentParser, blueprint: bool = True) -> None:
        p.add_argument("--data", default="data", help="Data directory containing manifest.json and CSVs")
        p.add_argument("--as-of", default=None, help="Observation date YYYY-MM-DD; defaults to today")
        p.add_argument("--audience-age", type=int, default=None, help="Audience minimum age for age-rating checks")
        if blueprint:
            p.add_argument("--blueprint", default=str(DEFAULT_BLUEPRINT))
            p.add_argument("--no-blueprint", action="store_true")
        p.add_argument("--recommendations", default=None)
        p.add_argument("--no-recommendations", action="store_true")

    analyze = sub.add_parser("analyze", help="Write Markdown and JSON coverage reports")
    add_common(analyze)
    analyze.add_argument("--version", default=None, help="Course version; defaults to latest and includes all-version index in JSON")
    analyze.add_argument("--out", default="reports")
    analyze.add_argument("--basename", default="coverage-report")
    analyze.add_argument("--generated-at", default=None)
    analyze.set_defaults(func=command_analyze)

    snapshot = sub.add_parser("snapshot", help="Write an immutable committee snapshot with source rows and hashes")
    add_common(snapshot)
    snapshot.add_argument("--version", default=None)
    snapshot.add_argument("--out", default="snapshots")
    snapshot.add_argument("--basename", default=None)
    snapshot.add_argument("--generated-at", default=None)
    snapshot.set_defaults(func=command_snapshot)

    validate = sub.add_parser("validate", parents=[common], help="Validate references, dates and feedback values")
    validate.add_argument("--strict", action="store_true", help="Exit non-zero on validation errors")
    validate.set_defaults(func=command_validate)

    impact = sub.add_parser("impact", help="Compare current data with a prior JSON snapshot/report")
    add_common(impact)
    impact.add_argument("--baseline", required=True)
    impact.add_argument("--out", default="reports")
    impact.add_argument("--basename", default="impact-report")
    impact.add_argument("--generated-at", default=None)
    impact.set_defaults(func=command_impact)

    adopt = sub.add_parser("adopt", help="Record an adopted recommendation and source-note hashes")
    adopt.add_argument("--data", default="data")
    adopt.add_argument("--register", default=str(PROJECT_ROOT / "state" / "adopted_recommendations.json"))
    adopt.add_argument("--id", required=True)
    adopt.add_argument("--text", required=True)
    adopt.add_argument("--topic", default="")
    adopt.add_argument("--segment", default="")
    adopt.add_argument("--version", default="")
    adopt.add_argument("--reference-ids", default="")
    adopt.add_argument("--adopted-at", default=None)
    adopt.add_argument("--as-of", default=None)
    adopt.add_argument("--audience-age", type=int, default=None)
    adopt.add_argument("--blueprint", default=str(DEFAULT_BLUEPRINT))
    adopt.add_argument("--no-blueprint", action="store_true")
    adopt.set_defaults(func=command_adopt)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
