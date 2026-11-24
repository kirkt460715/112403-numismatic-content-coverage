"""Adopted teaching recommendations and source-change revalidation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .hashing_compat import canonical_row_hash, note_hash
from .io import repository_snapshot


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value)
    return [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]


def normalize_recommendation(raw: Dict[str, Any]) -> Dict[str, Any]:
    rec = dict(raw)
    rec["recommendation_id"] = rec.get("recommendation_id") or rec.get("id") or ""
    rec["source_ids"] = _as_list(rec.get("source_ids"))
    rec["reference_ids"] = _as_list(rec.get("reference_ids"))
    rec["topic_id"] = rec.get("topic_id", "")
    rec["segment_id"] = rec.get("segment_id", "")
    rec["course_version"] = rec.get("course_version", "")
    rec["recommendation"] = rec.get("recommendation") or rec.get("text") or rec.get("advice") or ""
    rec["manual_status"] = rec.get("status", "adopted") or "adopted"
    hashes = rec.get("source_hashes") or rec.get("source_note_hashes") or {}
    if isinstance(hashes, str):
        # CSV cannot naturally store a JSON object; callers may pass JSON.
        import json

        try:
            hashes = json.loads(hashes)
        except json.JSONDecodeError:
            hashes = {}
    rec["stored_source_hashes"] = hashes if isinstance(hashes, dict) else {}
    row_hashes = rec.get("source_row_hashes") or {}
    rec["stored_source_row_hashes"] = row_hashes if isinstance(row_hashes, dict) else {}
    return rec


def _current_source_rows(analysis: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    snap = analysis.get("repository_snapshot") or {}
    files = snap.get("files", {})
    source_file = files.get("sources.csv")
    if source_file:
        return {row.get("source_id", ""): row for row in source_file.get("rows", []) if row.get("source_id")}
    return {}


def _scope_report_for(analysis: Dict[str, Any], version: str) -> Optional[Dict[str, Any]]:
    versions = analysis.get("version_reports") or {}
    if version and version in versions:
        return versions[version]
    report = analysis.get("report")
    if report and (not version or report.get("scope", {}).get("course_version") in {version, "ALL"}):
        return report
    if versions:
        # The recommendation may predate version labels; expose all rather
        # than pretending a version match.
        return next(iter(versions.values()))
    return report


def _topic_from_report(scope_report: Optional[Dict[str, Any]], topic_id: str) -> Optional[Dict[str, Any]]:
    if not scope_report:
        return None
    for topic in scope_report.get("topics", []):
        if topic.get("topic_id") == topic_id:
            return topic
    return None


def evaluate_recommendations(
    raw_records: List[Dict[str, Any]],
    analysis: Dict[str, Any],
    *,
    changed_source_ids: Optional[List[str]] = None,
    affected_reference_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    current_sources = _current_source_rows(analysis)
    changed_source_ids = set(changed_source_ids or [])
    affected_reference_ids = set(affected_reference_ids or [])
    evaluated: List[Dict[str, Any]] = []

    for raw in raw_records:
        rec = normalize_recommendation(raw)
        changes: List[Dict[str, Any]] = []

        for sid in rec["source_ids"]:
            current = current_sources.get(sid)
            if current is None:
                changes.append({"type": "source_missing", "source_id": sid})
                continue
            stored_note_hash = rec["stored_source_hashes"].get(sid)
            if stored_note_hash and stored_note_hash != note_hash(current):
                changes.append({"type": "source_note_corrected", "source_id": sid})
            stored_row_hash = rec["stored_source_row_hashes"].get(sid)
            if stored_row_hash and stored_row_hash != canonical_row_hash(current):
                changes.append({"type": "source_record_changed", "source_id": sid})
            if sid in changed_source_ids and not any(c.get("source_id") == sid for c in changes):
                changes.append({"type": "source_changed_in_revision", "source_id": sid})

        if affected_reference_ids:
            overlap = affected_reference_ids.intersection(rec["reference_ids"])
            for rid in sorted(overlap):
                changes.append({"type": "cited_reference_affected", "reference_id": rid})

        # Current source state from the selected source collection.
        source_states = {s.get("source_id"): s for s in analysis.get("report", {}).get("source_collection", {}).get("sources", [])}
        for sid in rec["source_ids"]:
            state = source_states.get(sid)
            if state and (state.get("blocked") or state.get("availability_state") not in {"available", "undated_scope", "unknown"}):
                changes.append(
                    {
                        "type": "source_unavailable_or_blocked",
                        "source_id": sid,
                        "availability_state": state.get("availability_state"),
                        "review_status_raw": state.get("review_status_raw"),
                    }
                )

        scope_report = _scope_report_for(analysis, rec["course_version"])
        topic = _topic_from_report(scope_report, rec["topic_id"])
        evidence = (topic or {}).get("evidence", {})
        coverage_class = (topic or {}).get("coverage_class")
        still_supported = bool(evidence.get("sufficient"))

        manual = rec.get("manual_status", "adopted")
        if manual in {"superseded", "revoked", "withdrawn"}:
            disposition = manual
            review_required = False
        elif changes:
            disposition = (
                "affected_needs_revalidation_coverage_retained"
                if still_supported
                else "affected_needs_revalidation_coverage_now_at_risk"
            )
            review_required = True
        else:
            disposition = "current"
            review_required = False

        evaluated.append(
            {
                "recommendation_id": rec["recommendation_id"],
                "course_version": rec["course_version"],
                "topic_id": rec["topic_id"],
                "segment_id": rec["segment_id"],
                "recommendation": rec["recommendation"],
                "source_ids": rec["source_ids"],
                "reference_ids": rec["reference_ids"],
                "manual_status": manual,
                "change_findings": changes,
                "review_required": review_required,
                "disposition": disposition,
                "topic_coverage_class_now": coverage_class,
                "topic_evidence_level_now": evidence.get("level"),
                "topic_still_evidence_supported": still_supported,
                "automatic_validity": "not_invalidated_without_review",
            }
        )

    summary = {
        "total": len(evaluated),
        "review_required": [r["recommendation_id"] for r in evaluated if r["review_required"]],
        "coverage_retained": [
            r["recommendation_id"]
            for r in evaluated
            if r["disposition"] == "affected_needs_revalidation_coverage_retained"
        ],
        "at_risk": [
            r["recommendation_id"]
            for r in evaluated
            if r["disposition"] == "affected_needs_revalidation_coverage_now_at_risk"
        ],
    }
    return {"summary": summary, "records": evaluated}


def recommendation_from_findings(
    recommendation_id: str,
    text: str,
    analysis: Dict[str, Any],
    *,
    topic_id: str = "",
    segment_id: str = "",
    course_version: str = "",
    reference_ids: Optional[List[str]] = None,
    adopted_at: str = "",
) -> Dict[str, Any]:
    """Create a register record with hashes that enable later correction checks."""
    reference_ids = reference_ids or []
    snap = analysis.get("repository_snapshot") or {"repository_snapshot": analysis.get("repository_snapshot")}
    repo_snapshot = analysis.get("repository_snapshot") or snap
    sources = _current_source_rows(analysis)
    if not sources and repo_snapshot:
        files = repo_snapshot.get("files", {})
        source_file = files.get("sources.csv", {})
        sources = {r.get("source_id", ""): r for r in source_file.get("rows", [])}
    references_file = (analysis.get("repository_snapshot") or {}).get("files", {}).get("references.csv", {})
    ref_rows = references_file.get("rows", [])
    source_ids = []
    for ref in ref_rows:
        if ref.get("reference_id") in reference_ids and ref.get("source_id") not in source_ids:
            source_ids.append(ref.get("source_id"))
    return {
        "recommendation_id": recommendation_id,
        "adopted_at": adopted_at,
        "course_version": course_version or analysis.get("scope", {}).get("course_version", ""),
        "topic_id": topic_id,
        "segment_id": segment_id,
        "recommendation": text,
        "reference_ids": reference_ids,
        "source_ids": source_ids,
        "source_hashes": {sid: note_hash(sources[sid]) for sid in source_ids if sid in sources},
        "source_row_hashes": {sid: canonical_row_hash(sources[sid]) for sid in source_ids if sid in sources},
        "status": "adopted",
    }
