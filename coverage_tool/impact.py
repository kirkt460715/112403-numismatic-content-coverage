"""Revision impact: source withdrawal/correction, structural edits and advice."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .analyzer import analyze_repository
from .hashing_compat import canonical_row_hash, note_hash
from .io import repository_snapshot, snapshot_to_repository
from .recommendations import evaluate_recommendations


def _index_rows(snapshot: Dict[str, Any], filename: str) -> Dict[str, Dict[str, str]]:
    files = snapshot.get("files", {})
    payload = files.get(filename)
    if not payload:
        return {}
    key = {
        "segments.csv": "segment_id",
        "topics.csv": "topic_id",
        "sources.csv": "source_id",
        "references.csv": "reference_id",
    }.get(filename)
    if key:
        return {row.get(key, ""): row for row in payload.get("rows", []) if row.get(key)}

    composite = {
        "segment_topics.csv": ("segment_id", "topic_id", "valid_from"),
        "feedback.csv": ("session_id", "segment_id", "topic_id"),
    }.get(filename)
    if composite:
        result = {}
        for row in payload.get("rows", []):
            identity = "|".join(row.get(part, "") for part in composite)
            result[identity] = row
        return result

    return {str(i): row for i, row in enumerate(payload.get("rows", []))}


def _table_changes(before_snapshot: Dict[str, Any], after_snapshot: Dict[str, Any], filename: str) -> Dict[str, Any]:
    before = _index_rows(before_snapshot, filename)
    after = _index_rows(after_snapshot, filename)
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = []
    for key in sorted(set(before) & set(after)):
        b, a = before[key], after[key]
        changed_fields = sorted({k for k in set(b) | set(a) if b.get(k, "") != a.get(k, "")})
        if changed_fields:
            changed.append({"id": key, "changed_fields": changed_fields, "before": b, "after": {k: a.get(k, "") for k in changed_fields}})
    return {"added": added, "removed": removed, "changed": changed}


def _topic_report(before_analysis: Dict[str, Any], version: str, topic_id: str) -> Optional[Dict[str, Any]]:
    scope = (before_analysis.get("version_reports") or {}).get(version) or before_analysis.get("report")
    for topic in (scope or {}).get("topics", []):
        if topic.get("topic_id") == topic_id:
            return topic
    return None


def compare_revisions(
    baseline_payload: Dict[str, Any],
    current_repo: Dict[str, Any],
    *,
    as_of: Optional[str] = None,
    audience_age: Optional[int] = None,
    recommendation_records: Optional[List[Dict[str, Any]]] = None,
    blueprint: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    before_snapshot = baseline_payload.get("repository_snapshot") if baseline_payload.get("repository_snapshot") else baseline_payload
    after_snapshot = repository_snapshot(current_repo)

    before_repo = snapshot_to_repository(before_snapshot)
    before_analysis = analyze_repository(
        before_repo,
        as_of=as_of,
        audience_age=audience_age,
        blueprint=blueprint,
    )
    after_analysis = analyze_repository(
        current_repo,
        as_of=as_of,
        audience_age=audience_age,
        blueprint=blueprint,
    )
    after_analysis["repository_snapshot"] = after_snapshot

    tracked_files = ["segments.csv", "topics.csv", "segment_topics.csv", "references.csv", "sources.csv", "feedback.csv"]
    table_changes = {filename: _table_changes(before_snapshot, after_snapshot, filename) for filename in tracked_files}

    before_sources = _index_rows(before_snapshot, "sources.csv")
    after_sources = _index_rows(after_snapshot, "sources.csv")
    source_changes = []
    changed_source_ids = set()
    for sid in sorted(set(before_sources) | set(after_sources)):
        before, after = before_sources.get(sid), after_sources.get(sid)
        if before is None:
            source_changes.append({"source_id": sid, "change_type": "added", "after": after})
            changed_source_ids.add(sid)
            continue
        if after is None:
            source_changes.append({"source_id": sid, "change_type": "removed", "before": before})
            changed_source_ids.add(sid)
            continue
        fields = sorted({k for k in set(before) | set(after) if before.get(k, "") != after.get(k, "")})
        if fields:
            if "source_note" in fields and note_hash(before) != note_hash(after):
                change_type = "source_note_corrected"
            elif {"review_status", "available_to"} & set(fields):
                change_type = "availability_or_review_changed"
            else:
                change_type = "source_record_changed"
            source_changes.append(
                {
                    "source_id": sid,
                    "change_type": change_type,
                    "changed_fields": fields,
                    "before": before,
                    "after": after,
                    "before_row_hash": canonical_row_hash(before),
                    "after_row_hash": canonical_row_hash(after),
                }
            )
            changed_source_ids.add(sid)

    # Find references and topic/version pairs connected to changed sources.
    before_refs = before_snapshot.get("files", {}).get("references.csv", {}).get("rows", [])
    after_refs = after_snapshot.get("files", {}).get("references.csv", {}).get("rows", [])
    union_refs = {r.get("reference_id"): r for r in before_refs + after_refs if r.get("reference_id")}
    changed_refs = [r for r in union_refs.values() if r.get("source_id") in changed_source_ids]
    affected_reference_ids = sorted({r.get("reference_id", "") for r in changed_refs})

    before_links = before_snapshot.get("files", {}).get("segment_topics.csv", {}).get("rows", [])
    after_links = after_snapshot.get("files", {}).get("segment_topics.csv", {}).get("rows", [])
    links_by_segment: Dict[str, set[str]] = {}
    for link in before_links + after_links:
        links_by_segment.setdefault(link.get("segment_id", ""), set()).add(link.get("topic_id", ""))

    topic_labels = {t.get("label", ""): t.get("topic_id") for t in after_snapshot.get("files", {}).get("topics.csv", {}).get("rows", [])}
    topic_ids = {t.get("topic_id", "") for t in after_snapshot.get("files", {}).get("topics.csv", {}).get("rows", [])}
    affected_pairs = set()
    affected_details = []
    for ref in changed_refs:
        version = ref.get("course_version", "") or after_analysis.get("scope", {}).get("course_version")
        direct_topic = topic_labels.get(ref.get("claim_topic", ""))
        if ref.get("claim_topic") in topic_ids:
            direct_topic = ref.get("claim_topic")
        candidate_topics = set(links_by_segment.get(ref.get("segment_id", ""), set()))
        if direct_topic:
            candidate_topics.add(direct_topic)
        for tid in candidate_topics:
            if not tid:
                continue
            pair = (version, tid, ref.get("source_id", ""), ref.get("reference_id", ""), direct_topic == tid)
            affected_pairs.add(pair)

    # Collapse source/ref dimensions into version/topic, retaining provenance.
    collapsed: Dict[tuple[str, str], Dict[str, Any]] = {}
    for version, tid, sid, rid, direct in affected_pairs:
        key = (version, tid)
        item = collapsed.setdefault(
            key,
            {
                "course_version": version,
                "topic_id": tid,
                "source_ids": set(),
                "reference_ids": set(),
                "directly_claimed": False,
            },
        )
        item["source_ids"].add(sid)
        item["reference_ids"].add(rid)
        item["directly_claimed"] = item["directly_claimed"] or direct

    for (version, tid), item in sorted(collapsed.items()):
        before_topic = _topic_report(before_analysis, version, tid)
        after_topic = _topic_report(after_analysis, version, tid)
        before_ev = (before_topic or {}).get("evidence", {})
        after_ev = (after_topic or {}).get("evidence", {})
        retained = bool(after_ev.get("sufficient"))
        affected_details.append(
            {
                "course_version": version,
                "topic_id": tid,
                "source_ids": sorted(item["source_ids"]),
                "reference_ids": sorted(item["reference_ids"]),
                "directly_claimed": item["directly_claimed"],
                "coverage_before": (before_topic or {}).get("coverage_class"),
                "coverage_after": (after_topic or {}).get("coverage_class"),
                "evidence_before": before_ev.get("level"),
                "evidence_after": after_ev.get("level"),
                "remaining_source_ids": after_ev.get("source_ids", []),
                "remaining_independent_source_count": after_ev.get("independent_source_count", 0),
                "other_evidence_sufficient": retained,
                "impact_label": (
                    "reassess_cited_claims_but_topic_coverage_retained"
                    if retained and before_ev.get("level") != after_ev.get("level")
                    else "reassess_cited_claims_and_topic_now_at_risk"
                    if not retained
                    else "reassess_cited_claims_topic_evidence_still_sufficient"
                ),
            }
        )

    recommendations = None
    if recommendation_records is not None:
        recommendations = evaluate_recommendations(
            recommendation_records,
            after_analysis,
            changed_source_ids=sorted(changed_source_ids),
            affected_reference_ids=affected_reference_ids,
        )

    new_segments = table_changes["segments.csv"]["added"]
    removed_segments = table_changes["segments.csv"]["removed"]
    return {
        "schema_version": 1,
        "as_of": as_of,
        "audience_age": audience_age,
        "source_changes": source_changes,
        "table_changes": table_changes,
        "affected_reference_ids": affected_reference_ids,
        "affected_topics": affected_details,
        "new_segment_ids_auto_included": new_segments,
        "removed_segment_ids": removed_segments,
        "recommendations": recommendations,
        "after_analysis": after_analysis,
        "explanation": [
            "来源更正或撤下只直接影响引用它的 reference、段落和主题。",
            "主题是否失效由剩余独立可用证据重新计算；其他充分证据会保留覆盖结论，但被更正来源支撑的教学建议仍需复核。",
            "新增 segment 行已由同一加载器和覆盖规则自动纳入。",
        ],
    }
