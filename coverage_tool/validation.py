"""Referential and value validation.

The analyzer is deliberately tolerant: a bad row is reported as an issue and
excluded from the relevant calculation rather than making the whole committee
report unavailable.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .dates import parse_date
from .io import rows


def issue(level: str, code: str, message: str, **context: Any) -> Dict[str, Any]:
    result = {"level": level, "code": code, "message": message}
    if context:
        result["context"] = context
    return result


def _check_date_order(row: Dict[str, str], fields: tuple[str, str], label: str, issues: List[Dict[str, Any]]) -> None:
    start_field, end_field = fields
    try:
        start = parse_date(row.get(start_field, ""), start_field)
        end = parse_date(row.get(end_field, ""), end_field)
    except ValueError as exc:
        issues.append(issue("error", "invalid_date", str(exc), row=row, table=label))
        return
    if start and end and start > end:
        issues.append(
            issue(
                "error",
                "invalid_interval",
                f"{label}: {start_field} is after {end_field}",
                row=row,
            )
        )


def validate_repository(repo: Dict[str, Any]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    segments = {row["segment_id"]: row for row in rows(repo, "segments") if row.get("segment_id")}
    topics = {row["topic_id"]: row for row in rows(repo, "topics") if row.get("topic_id")}
    sources = {row["source_id"]: row for row in rows(repo, "sources") if row.get("source_id")}

    if not segments:
        issues.append(issue("error", "missing_segments", "No course segments were loaded."))
    if not topics:
        issues.append(issue("error", "missing_topics", "No history topics were loaded."))

    seen_segment_ids = set()
    for row in rows(repo, "segments"):
        sid = row.get("segment_id", "")
        if not sid:
            issues.append(issue("error", "empty_segment_id", "Segment row has no segment_id", row=row))
        elif sid in seen_segment_ids:
            issues.append(issue("error", "duplicate_segment_id", f"Duplicate segment_id {sid}", segment_id=sid))
        seen_segment_ids.add(sid)
        for field in ("position", "duration_min"):
            try:
                value = int(row.get(field, "") or 0)
                if value < 0:
                    raise ValueError
            except ValueError:
                issues.append(issue("error", "invalid_integer", f"segments.{field} must be non-negative integer", segment_id=sid, value=row.get(field)))

    seen_topic_ids = set()
    for row in rows(repo, "topics"):
        tid = row.get("topic_id", "")
        if tid in seen_topic_ids:
            issues.append(issue("error", "duplicate_topic_id", f"Duplicate topic_id {tid}", topic_id=tid))
        seen_topic_ids.add(tid)
        if row.get("required", "").strip().lower() not in {"yes", "no", "true", "false", "1", "0", "是", "否", ""}:
            issues.append(issue("warning", "nonliteral_required", "required should be yes/no", topic_id=tid, value=row.get("required")))

    for row in rows(repo, "segment_topics"):
        sid, tid = row.get("segment_id", ""), row.get("topic_id", "")
        if sid not in segments:
            issues.append(issue("error", "dangling_segment_topic", "segment_topics references missing segment", segment_id=sid, topic_id=tid))
        if tid not in topics:
            issues.append(issue("error", "dangling_topic", "segment_topics references missing topic", segment_id=sid, topic_id=tid))
        _check_date_order(row, ("valid_from", "valid_to"), "segment_topics", issues)

    for row in rows(repo, "sources"):
        source_id = row.get("source_id", "")
        _check_date_order(row, ("available_from", "available_to"), "sources", issues)
        if not row.get("review_status", ""):
            issues.append(issue("warning", "empty_review_status", "Source review_status is empty and is not assumed approved", source_id=source_id))

    topic_labels = {row.get("label", ""): tid for tid, row in topics.items()}
    for row in rows(repo, "references"):
        rid = row.get("reference_id", "")
        sid, source_id = row.get("segment_id", ""), row.get("source_id", "")
        if sid not in segments:
            issues.append(issue("error", "dangling_reference_segment", "reference references missing segment", reference_id=rid, segment_id=sid))
        if source_id not in sources:
            issues.append(issue("error", "dangling_reference_source", "reference references missing source", reference_id=rid, source_id=source_id))
        claim = row.get("claim_topic", "")
        if claim and claim not in topic_labels and claim not in topics:
            issues.append(
                issue(
                    "warning",
                    "unmapped_claim_topic",
                    "claim_topic has no exact topic_id/label and cannot be counted as direct topic evidence",
                    reference_id=rid,
                    claim_topic=claim,
                )
            )
        segment = segments.get(sid)
        ref_version = row.get("course_version", "")
        if segment and ref_version and segment.get("course_version") and ref_version != segment.get("course_version"):
            issues.append(
                issue(
                    "warning",
                    "reference_version_mismatch",
                    "reference.course_version differs from segment.course_version",
                    reference_id=rid,
                    segment_version=segment.get("course_version"),
                    reference_version=ref_version,
                )
            )

    for row in rows(repo, "feedback"):
        sid, tid = row.get("segment_id", ""), row.get("topic_id", "")
        if sid not in segments:
            issues.append(issue("error", "dangling_feedback_segment", "feedback references missing stable segment_id; preserve it for historical trace", segment_id=sid))
        if tid not in topics:
            issues.append(issue("warning", "unknown_feedback_topic", "feedback topic_id is absent from topics table", topic_id=tid, segment_id=sid))
        try:
            understood = int(row.get("understood_count", "") or 0)
            respondents = int(row.get("respondent_count", "") or 0)
            if understood < 0 or respondents < 0 or understood > respondents:
                issues.append(issue("error", "invalid_feedback_counts", "Require 0 <= understood_count <= respondent_count", row=row))
        except ValueError:
            issues.append(issue("error", "invalid_feedback_counts", "Feedback counts must be integers", row=row))

    return issues
