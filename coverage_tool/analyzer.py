"""Core coverage, evidence, feedback and sequence analysis."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .feedback import feedback_record, summarise_feedback
from .io import load_json, rows
from .sources import evaluate_source, evidence_strength
from .taxonomy import classify_relation, infer_era, load_blueprint
from .validation import validate_repository


def _truthy(value: str) -> bool:
    return (value or "").strip().lower() in {"yes", "true", "1", "y", "是"}


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _profiles_from_repo(repo: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    return {row.get("source_id", ""): row for row in rows(repo, "source_profiles") if row.get("source_id")}


def _lineage_from_repo(repo: Dict[str, Any]) -> List[Dict[str, str]]:
    records: List[Dict[str, str]] = []
    for table_name in ("segment_lineage", "lineage"):
        for raw in rows(repo, table_name):
            old = (
                raw.get("old_segment_id")
                or raw.get("parent_segment_id")
                or raw.get("source_segment_id")
                or raw.get("predecessor_segment_id")
                or ""
            )
            new = (
                raw.get("new_segment_id")
                or raw.get("child_segment_id")
                or raw.get("target_segment_id")
                or raw.get("successor_segment_id")
                or ""
            )
            records.append(
                {
                    "old_segment_id": old,
                    "new_segment_id": new,
                    "relation_type": raw.get("relation_type") or raw.get("change_type") or raw.get("lineage_type") or "successor",
                    "effective_from": raw.get("effective_from", ""),
                    "note": raw.get("note", ""),
                    "automatic_feedback_reattribution": "false",
                }
            )
    return records


def load_recommendation_records(path: Optional[str]) -> List[Dict[str, Any]]:
    if not path:
        return []
    if str(path).endswith(".json"):
        payload = load_json(path)
        if isinstance(payload, dict) and "recommendations" in payload:
            return list(payload["recommendations"])
        if isinstance(payload, list):
            return payload
        return []
    # CSV is handled through the repository loader in the CLI when placed in
    # data/, but this helper also accepts an explicit CSV path.
    from .io import read_csv

    _, records = read_csv(path)
    normalised = []
    for row in records:
        item = dict(row)
        for key in ("reference_ids", "source_ids"):
            if isinstance(item.get(key), str):
                item[key] = [part.strip() for part in item[key].replace(";", ",").split(",") if part.strip()]
        normalised.append(item)
    return normalised


def analyze_scope(
    repo: Dict[str, Any],
    course_version: Optional[str] = None,
    *,
    as_of: Optional[str] = None,
    audience_age: Optional[int] = None,
    blueprint: Optional[Dict[str, Any]] = None,
    source_profiles: Optional[Dict[str, Dict[str, str]]] = None,
    low_understanding_threshold: float = 0.6,
) -> Dict[str, Any]:
    all_segments = rows(repo, "segments")
    all_segment_ids = {s.get("segment_id", "") for s in all_segments}
    if course_version and course_version != "ALL":
        segments = [s for s in all_segments if s.get("course_version") == course_version]
    else:
        segments = list(all_segments)

    segment_ids = {s.get("segment_id", "") for s in segments}
    segment_by_id = {s.get("segment_id", ""): s for s in segments}
    topics = rows(repo, "topics")
    topic_by_id = {t.get("topic_id", ""): t for t in topics}
    label_to_topic_id = {t.get("label", ""): t.get("topic_id", "") for t in topics if t.get("label")}

    profiles = _profiles_from_repo(repo)
    if source_profiles:
        profiles.update(source_profiles)

    source_rows = {s.get("source_id", ""): s for s in rows(repo, "sources")}
    source_evaluations: Dict[str, Dict[str, Any]] = {}
    for sid, source in source_rows.items():
        evaluated = evaluate_source(
            source,
            as_of=as_of,
            audience_age=audience_age,
            profile=profiles.get(sid),
        )
        source_evaluations[sid] = evaluated

    sessions = {s.get("session_id", ""): s for s in rows(repo, "sessions")}
    lineage = _lineage_from_repo(repo)
    descendants: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for edge in lineage:
        if edge["old_segment_id"]:
            descendants[edge["old_segment_id"]].append(edge)

    # References are versioned provenance records.  When a concrete version is
    # requested, its course_version is authoritative; segment attachment is
    # retained for mismatch diagnostics.
    all_references = rows(repo, "references")
    if course_version and course_version != "ALL":
        version_references = [r for r in all_references if r.get("course_version") == course_version]
        # Be tolerant of fixtures that leave reference.course_version blank:
        # attach those if their segment belongs to this version.
        version_reference_ids = {r.get("reference_id") for r in version_references}
        for ref in all_references:
            if ref.get("reference_id") in version_reference_ids:
                continue
            if not ref.get("course_version") and ref.get("segment_id") in segment_ids:
                version_references.append(ref)
    else:
        version_references = list(all_references)

    references: List[Dict[str, Any]] = []
    for ref in version_references:
        claim = ref.get("claim_topic", "")
        mapped_topic = label_to_topic_id.get(claim) or (claim if claim in topic_by_id else None)
        source_eval = dict(source_evaluations.get(ref.get("source_id", ""), {
            "source_id": ref.get("source_id", ""),
            "currently_usable": False,
            "availability_state": "source_missing",
            "trust_tier": "missing",
        }))
        item = dict(ref)
        item.update(
            {
                "mapped_topic_id": mapped_topic,
                "claim_alignment": "direct" if mapped_topic else "unmapped_claim_requires_scope_review",
                "source": source_eval,
            }
        )
        references.append(item)

    links_by_segment_topic: Dict[tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    links_by_topic: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for link in rows(repo, "segment_topics"):
        sid, tid = link.get("segment_id", ""), link.get("topic_id", "")
        if sid not in segment_ids:
            continue
        relation = classify_relation(link.get("relation", ""))
        active = None
        if as_of:
            from .dates import interval_active
            active = interval_active(as_of, link.get("valid_from", ""), link.get("valid_to", ""))
        enriched_link = {**link, "relation_classification": relation, "active_on_as_of": active}
        links_by_segment_topic[(sid, tid)].append(enriched_link)
        links_by_topic[tid].append(enriched_link)

    feedback_by_segment: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    feedback_by_segment_topic: Dict[tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    feedback_orphans: List[Dict[str, Any]] = []
    out_of_version_feedback: List[Dict[str, Any]] = []
    for raw_fb in rows(repo, "feedback"):
        fb = feedback_record(raw_fb, low_understanding_threshold)
        session = sessions.get(fb["session_id"], {})
        fb["session_date"] = session.get("session_date") or raw_fb.get("session_date") or None
        fb["course_version_from_session"] = session.get("course_version") or None
        sid = fb["segment_id"]
        if fb["session_date"]:
            from .dates import interval_active

            periods = []
            for link in links_by_segment_topic.get((sid, fb["topic_id"]), []):
                periods.append(
                    {
                        "relation": link.get("relation"),
                        "valid_from": link.get("valid_from"),
                        "valid_to": link.get("valid_to"),
                        "active_on_session_date": interval_active(
                            fb["session_date"], link.get("valid_from", ""), link.get("valid_to", "")
                        ),
                    }
                )
            fb["relation_periods_at_session"] = periods
            fb["active_relation_on_session"] = [p for p in periods if p.get("active_on_session_date")]
        if sid in segment_by_id:
            feedback_by_segment[sid].append(fb)
            feedback_by_segment_topic[(sid, fb["topic_id"])].append(fb)
        elif sid in all_segment_ids:
            fb["attribution_policy"] = "retain_original_version_segment_id"
            out_of_version_feedback.append(fb)
        else:
            fb["attribution_policy"] = "retain_missing_historical_segment_id"
            fb["lineage_descendants"] = descendants.get(sid, [])
            feedback_orphans.append(fb)

    reference_by_segment: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for ref in references:
        reference_by_segment[ref.get("segment_id", "")].append(ref)

    segment_reports: List[Dict[str, Any]] = []
    for segment in sorted(segments, key=lambda s: (_int_or_none(s.get("position")) is None, _int_or_none(s.get("position")) or 0, s.get("segment_id", ""))):
        sid = segment.get("segment_id", "")
        segment_topics = []
        segment_text_parts = [segment.get("title", "")]
        for tid in sorted({link.get("topic_id", "") for link in rows(repo, "segment_topics") if link.get("segment_id") == sid}):
            topic = topic_by_id.get(tid, {})
            segment_text_parts.extend([topic.get("label", ""), topic.get("period", "")])
            for link in links_by_segment_topic.get((sid, tid), []):
                segment_topics.append(
                    {
                        "topic_id": tid,
                        "label": topic.get("label", ""),
                        **link,
                    }
                )
        segment_refs = reference_by_segment.get(sid, [])
        segment_text_parts.extend([r.get("claim_topic", "") for r in segment_refs])
        era = infer_era(" ".join(part for part in segment_text_parts if part), blueprint)
        segment_report = {
            "segment_id": sid,
            "course_version": segment.get("course_version", ""),
            "position": _int_or_none(segment.get("position")),
            "duration_min": _int_or_none(segment.get("duration_min")),
            "title": segment.get("title", ""),
            "era": era,
            "topic_links": segment_topics,
            "references": [
                {
                    "reference_id": r.get("reference_id"),
                    "source_id": r.get("source_id"),
                    "claim_topic": r.get("claim_topic"),
                    "mapped_topic_id": r.get("mapped_topic_id"),
                    "claim_alignment": r.get("claim_alignment"),
                    "course_version": r.get("course_version"),
                    "source_summary": {
                        "object_token": r["source"].get("object_token"),
                        "review_status_raw": r["source"].get("review_status_raw"),
                        "trust_tier": r["source"].get("trust_tier"),
                        "availability_state": r["source"].get("availability_state"),
                        "currently_usable": r["source"].get("currently_usable"),
                        "age_status": r["source"].get("age", {}).get("status"),
                    },
                }
                for r in segment_refs
            ],
            "feedback": feedback_by_segment.get(sid, []),
        }
        segment_reports.append(segment_report)

    topic_reports: List[Dict[str, Any]] = []
    for topic in topics:
        tid = topic.get("topic_id", "")
        links = list(links_by_topic.get(tid, []))
        # Restrict links to in-scope segments (links_by_topic was already).
        ordered_links = sorted(
            links,
            key=lambda link: (
                _int_or_none(segment_by_id.get(link.get("segment_id", ""), {}).get("position")) is None,
                _int_or_none(segment_by_id.get(link.get("segment_id", ""), {}).get("position")) or 0,
                link.get("segment_id", ""),
            ),
        )
        classes = [link["relation_classification"]["class"] for link in ordered_links]
        explanatory = [link for link in ordered_links if link["relation_classification"].get("explanatory")]
        shallow = [
            link
            for link in ordered_links
            if link["relation_classification"].get("class") in {"introductory", "descriptive", "illustrative", "contextual"}
        ]
        active_links = [link for link in ordered_links if link.get("active_on_as_of") is True]
        if ordered_links:
            if explanatory:
                teaching_status = "explained"
            elif shallow and len(shallow) == len([l for l in ordered_links if l["relation_classification"]["class"] != "empty"]):
                teaching_status = "introduced_or_illustrated_only"
            else:
                teaching_status = "tagged_relation_unclassified"
        elif feedback_by_segment_topic_keys(feedback_by_segment_topic, segment_ids, tid):
            teaching_status = "feedback_only_topic_without_segment_topic"
        else:
            teaching_status = "absent"

        direct_refs = [r for r in references if r.get("mapped_topic_id") == tid]
        source_evidence = []
        for ref in direct_refs:
            source_eval = dict(ref["source"])
            source_eval["claim_alignment"] = "direct"
            source_eval["reference_id"] = ref.get("reference_id")
            source_eval["claim_topic"] = ref.get("claim_topic")
            source_evidence.append(source_eval)
        evidence = evidence_strength(source_evidence)

        topic_feedback: List[Dict[str, Any]] = []
        for sid in sorted(segment_ids):
            topic_feedback.extend(feedback_by_segment_topic.get((sid, tid), []))
        historical_feedback = [
            fb
            for fb in feedback_orphans
            if fb.get("topic_id") == tid
        ]
        fb_summary = summarise_feedback(topic_feedback)
        historical_fb_summary = summarise_feedback(historical_feedback)

        segment_positions = []
        for link in ordered_links:
            seg = segment_by_id.get(link.get("segment_id", ""), {})
            segment_positions.append(
                {
                    "segment_id": link.get("segment_id"),
                    "position": _int_or_none(seg.get("position")),
                    "relation": link.get("relation"),
                    "relation_class": link["relation_classification"].get("class"),
                    "active_on_as_of": link.get("active_on_as_of"),
                    "valid_from": link.get("valid_from"),
                    "valid_to": link.get("valid_to"),
                }
            )

        findings: List[str] = []
        if teaching_status == "absent":
            findings.append("没有课程段落标注该主题；段落数量不能替代这项缺口判断。")
        if teaching_status == "feedback_only_topic_without_segment_topic":
            findings.append("反馈记录了该主题，但 segment_topics 缺少对应标注；需补标注以保留讲述内容。")
        if ordered_links and not explanatory:
            findings.append("只有介绍、背景、例子或外形/描述性关系，缺少解释货币、信用与地方经济因果联系的段落。")
        if len({link.get("segment_id") for link in ordered_links}) >= 2 and not explanatory:
            findings.append("多个段落停留在浅层或器物外形重复，可能是重复介绍而非主题深化。")
        if evidence["level"] == "none":
            findings.append("缺少精确映射到该主题的来源引用；馆藏叙述可能未建立证据链。")
        elif evidence["level"] == "lapsed_or_withdrawn":
            findings.append("原有直接来源已不可用、被撤下或审核驳回，当前证据需重新确认。")
        elif evidence["level"] == "provisional":
            findings.append("直接来源仍为 review/待核状态，证据只能作暂定支持。")
        elif not evidence["sufficient"]:
            findings.append(evidence["rationale"])
        for fb in topic_feedback:
            if fb.get("low_understanding"):
                findings.append(f"{fb['session_id']}/{fb['segment_id']} 理解率偏低（{fb['understanding_rate']:.0%}），但这不是历史可靠性判断。")

        coverage_class = _coverage_class(topic, teaching_status, evidence)
        topic_reports.append(
            {
                "topic_id": tid,
                "label": topic.get("label", ""),
                "period": topic.get("period", ""),
                "required": _truthy(topic.get("required", "")),
                "teaching_status": teaching_status,
                "coverage_class": coverage_class,
                "relation_classes": classes,
                "has_explanatory_relation": bool(explanatory),
                "active_link_count_on_as_of": len(active_links) if as_of else None,
                "link_count": len(ordered_links),
                "segment_count": len({link.get("segment_id") for link in ordered_links}),
                "segments": segment_positions,
                "evidence": evidence,
                "references": [
                    {
                        "reference_id": r.get("reference_id"),
                        "segment_id": r.get("segment_id"),
                        "source_id": r.get("source_id"),
                        "claim_topic": r.get("claim_topic"),
                        "course_version": r.get("course_version"),
                        "source": r.get("source"),
                    }
                    for r in direct_refs
                ],
                "feedback": topic_feedback,
                "feedback_summary": fb_summary,
                "historical_feedback": historical_feedback,
                "historical_feedback_summary": historical_fb_summary,
                "findings": findings,
            }
        )

    sequence_findings = _sequence_findings(segment_reports, topic_reports)
    source_collection = _source_collection_report(source_evaluations, references, rows(repo, "sources"), as_of, audience_age)
    arc = evaluate_curriculum_arc(segment_reports, topic_reports, blueprint or {})

    required_topics = [t for t in topic_reports if t["required"]]

    def rate(numerator: int, denominator: int) -> Optional[float]:
        return round(numerator / denominator, 4) if denominator else None

    scheduled_required = [t for t in required_topics if t["teaching_status"] != "absent"]
    evidence_sufficient_required = [t for t in required_topics if t["evidence"].get("sufficient")]
    depth_adequate_required = [t for t in required_topics if t.get("has_explanatory_relation")]
    complete_required = [t for t in required_topics if t["coverage_class"] in {"covered", "strong_coverage"}]
    summary = {
        "course_version": course_version or "ALL",
        "segment_count": len(segment_reports),
        "total_duration_min": sum(s["duration_min"] or 0 for s in segment_reports),
        "required_topic_count": len(required_topics),
        "required_topic_rates": {
            "scheduled": rate(len(scheduled_required), len(required_topics)),
            "explanatory_depth": rate(len(depth_adequate_required), len(required_topics)),
            "evidence_sufficient": rate(len(evidence_sufficient_required), len(required_topics)),
            "complete_coverage": rate(len(complete_required), len(required_topics)),
        },
        "coverage_class_counts": _count_by(topic_reports, "coverage_class"),
        "gap_topics": [t["topic_id"] for t in required_topics if t["coverage_class"] == "gap"],
        "evidence_gap_topics": [t["topic_id"] for t in topic_reports if t["evidence"]["level"] in {"none", "lapsed_or_withdrawn", "weak", "unrated"}],
        "provisional_topics": [t["topic_id"] for t in topic_reports if t["evidence"]["level"] == "provisional"],
        "depth_gap_topics": [t["topic_id"] for t in topic_reports if not t["has_explanatory_relation"] and t["teaching_status"] != "absent"],
        "low_understanding_topics": sorted({fb["topic_id"] for s in segment_reports for fb in s["feedback"] if fb.get("low_understanding")}),
        "age_restricted_used_source_ids": [
            s.get("source_id")
            for s in source_collection.get("sources", [])
            if s.get("used_in_scope") and s.get("age", {}).get("status") == "restricted"
        ],
        "age_unknown_source_ids": source_collection.get("age_unknown_source_ids", []),
        "orphan_feedback_count": len(feedback_orphans),
        "out_of_version_feedback_count": len(out_of_version_feedback),
    }

    return {
        "scope": {"course_version": course_version or "ALL", "as_of": as_of, "audience_age": audience_age},
        "summary": summary,
        "segments": segment_reports,
        "topics": topic_reports,
        "sequence_findings": sequence_findings,
        "curriculum_arc": arc,
        "lineage": lineage,
        "source_collection": source_collection,
        "orphan_feedback": feedback_orphans,
        "out_of_version_feedback": out_of_version_feedback,
        "method_notes": [
            "覆盖由必需主题、讲述关系深度和可用独立证据决定，不使用段落数量作为充分性标准。",
            "反馈只表示理解度/参与度，不证明来源或历史解释可靠。",
            "旧反馈按稳定 segment_id 保留；拆段/合段后不自动改挂到新段落。",
            "claim_topic 必须精确对应 topics.label 或 topic_id 才计为直接证据；近似说法进入来源范围复核。",
        ],
    }


def feedback_by_segment_topic_keys(mapping, segment_ids, topic_id) -> bool:
    return any(key[1] == topic_id and key[0] in segment_ids and mapping.get(key) for key in mapping)


def _coverage_class(topic: Dict[str, str], teaching_status: str, evidence: Dict[str, Any]) -> str:
    required = _truthy(topic.get("required", ""))
    if teaching_status == "absent":
        return "gap" if required else "optional_not_scheduled"
    if teaching_status == "feedback_only_topic_without_segment_topic":
        return "annotation_gap"
    if evidence["level"] in {"none", "lapsed_or_withdrawn"}:
        return "evidence_gap"
    if not teaching_status == "explained":
        return "explanation_depth_gap" if evidence["sufficient"] else "needs_depth_and_evidence"
    if evidence["level"] == "strong":
        return "strong_coverage"
    if evidence["sufficient"]:
        return "covered"
    return "evidence_limited"


def _count_by(items: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    result: Dict[str, int] = defaultdict(int)
    for item in items:
        result[str(item.get(key))] += 1
    return dict(sorted(result.items()))


def _sequence_findings(segments: List[Dict[str, Any]], topics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    positions = [s["position"] for s in segments if s["position"] is not None]
    if len(positions) != len(set(positions)):
        findings.append({"level": "warning", "code": "duplicate_position", "message": "存在相同 position，讲述顺序需要教研确认。"})
    if positions and sorted(positions) != list(range(min(positions), max(positions) + 1)):
        findings.append({"level": "info", "code": "position_gap", "message": "position 不连续；拆段/合段后请确认是否为有意编号。"})

    ordered = [s for s in segments if s.get("position") is not None]
    for prev, nxt in zip(ordered, ordered[1:]):
        prev_era = (prev.get("era") or {}).get("order")
        next_era = (nxt.get("era") or {}).get("order")
        if prev_era and next_era and next_era < prev_era:
            findings.append(
                {
                    "level": "info",
                    "code": "chronology_regression",
                    "message": f"{prev['segment_id']}→{nxt['segment_id']} 出现年代回跳；若作为地方专题或比较回旋，应加过渡说明。",
                    "segment_ids": [prev["segment_id"], nxt["segment_id"]],
                    "eras": [(prev.get("era") or {}).get("era"), (nxt.get("era") or {}).get("era")],
                }
            )

    for topic in topics:
        seg_entries = [s for s in topic.get("segments", []) if s.get("position") is not None]
        if len(seg_entries) >= 2 and all(s.get("relation_class") in {"introductory", "descriptive", "illustrative", "contextual", "unclassified", "empty"} for s in seg_entries):
            findings.append(
                {
                    "level": "warning",
                    "code": "shallow_repetition",
                    "message": f"{topic['topic_id']}《{topic['label']}》在多个段落重复，但没有 explains/分析/联系类关系；需合并外形介绍或补因果解释。",
                    "topic_id": topic["topic_id"],
                    "segment_ids": [s["segment_id"] for s in seg_entries],
                }
            )

    for segment in segments:
        duration = segment.get("duration_min") or 0
        links = segment.get("topic_links", [])
        has_explanation = any(link.get("relation_classification", {}).get("explanatory") for link in links)
        shallow_links = [
            link
            for link in links
            if link.get("relation_classification", {}).get("class")
            in {"introductory", "descriptive", "illustrative", "contextual"}
        ]
        if duration >= 8 and links and not has_explanation and len(shallow_links) == len(links):
            findings.append(
                {
                    "level": "info",
                    "code": "long_shallow_segment",
                    "message": (
                        f"{segment['segment_id']} 时长 {duration} 分钟，但主题关系均为介绍/描述/例证/背景；"
                        "请核查是否把较多时间用于重复器物外形，而没有解释货币、信用或地方经济联系。"
                    ),
                    "segment_id": segment["segment_id"],
                    "duration_min": duration,
                }
            )
    return findings


def _source_collection_report(
    source_evaluations: Dict[str, Dict[str, Any]],
    references: List[Dict[str, Any]],
    source_rows: List[Dict[str, str]],
    as_of: Optional[str],
    audience_age: Optional[int],
) -> Dict[str, Any]:
    used_source_ids = {r.get("source_id") for r in references}
    ref_count: Dict[str, int] = defaultdict(int)
    for r in references:
        ref_count[r.get("source_id", "")] += 1
    sources = []
    for sid, evaluation in source_evaluations.items():
        item = dict(evaluation)
        item["reference_count_in_scope"] = ref_count.get(sid, 0)
        item["used_in_scope"] = sid in used_source_ids
        sources.append(item)
    unused_available = [s["source_id"] for s in sources if not s["used_in_scope"] and s.get("currently_usable")]
    scope_review = [
        {"reference_id": r.get("reference_id"), "segment_id": r.get("segment_id"), "claim_topic": r.get("claim_topic")}
        for r in references
        if r.get("claim_alignment", "").startswith("unmapped")
    ]
    age_unknown = [s["source_id"] for s in sources if s.get("age", {}).get("status") in {"unknown", "unrated"}]
    return {
        "as_of": as_of,
        "audience_age": audience_age,
        "sources": sources,
        "unused_available_source_ids": unused_available,
        "unmapped_claims": scope_review,
        "age_unknown_source_ids": age_unknown,
        "collection_actions": [
            "确认 blocked/availability_window_closed 材料已从当前课程撤下。",
            "精确复核 unmapped_claims：近似主题不能自动视为来源已支持。",
            "为 age_unknown_source_ids 补充适合年龄；未知不等于全年龄。",
        ],
    }


def evaluate_curriculum_arc(
    segment_reports: List[Dict[str, Any]],
    topic_reports: List[Dict[str, Any]],
    blueprint: Dict[str, Any],
) -> Dict[str, Any]:
    requirements = blueprint.get("arc_requirements", [])
    topic_by_id = {t["topic_id"]: t for t in topic_reports}
    searchable = []
    segment_topic_ids: Dict[str, set[str]] = {}
    for segment in segment_reports:
        text = " ".join(
            [segment.get("title", "")]
            + [link.get("label", "") for link in segment.get("topic_links", [])]
            + [ref.get("claim_topic", "") for ref in segment.get("references", [])]
        )
        searchable.append((segment["segment_id"], text))
        segment_topic_ids[segment["segment_id"]] = {
            link.get("topic_id", "") for link in segment.get("topic_links", []) if link.get("topic_id")
        }

    results = []
    for req in requirements:
        explicit_ids = req.get("topic_ids", [])
        explicit_id_set = set(explicit_ids)
        explicit = []
        explicit_metadata_text = []
        for tid in explicit_ids:
            topic = topic_by_id.get(tid)
            if topic and topic.get("teaching_status") != "absent":
                explicit.append({"topic_id": tid, "coverage_class": topic.get("coverage_class")})
                explicit_metadata_text.extend([topic.get("label", ""), topic.get("period", "")])
        keywords = req.get("any_keywords", [])
        keyword_hits = []
        co_located_hits = []
        for sid, text in searchable:
            hits = [word for word in keywords if str(word).lower() in text.lower()]
            if hits:
                hit = {"segment_id": sid, "matched_keywords": hits}
                keyword_hits.append(hit)
                if explicit_id_set & segment_topic_ids.get(sid, set()):
                    co_located_hits.append(hit)
        metadata_hits = [
            word
            for word in keywords
            if any(str(word).lower() in text.lower() for text in explicit_metadata_text)
        ]
        if explicit and (co_located_hits or metadata_hits):
            status = "explicitly_scheduled_with_text_signal"
        elif explicit:
            # A keyword in some other segment must not be treated as proof
            # that the broad explicit topic actually covers that specific point.
            status = "explicit_broad_topic_verify_specifics"
        elif keyword_hits:
            status = "keyword_signal_requires_topic_tag"
        else:
            status = "gap"
        results.append(
            {
                "requirement_id": req.get("id"),
                "label": req.get("label"),
                "era": req.get("era"),
                "required": req.get("required", True),
                "status": status,
                "explicit_topics": explicit,
                "keyword_hits": keyword_hits,
                "co_located_keyword_hits": co_located_hits,
                "metadata_keyword_hits": metadata_hits,
                "advice": req.get("advice", ""),
            }
        )
    gaps = [r["requirement_id"] for r in results if r["status"] == "gap" and r["required"]]
    tagging = [r["requirement_id"] for r in results if r["status"] == "keyword_signal_requires_topic_tag"]
    return {"requirements": results, "gap_requirement_ids": gaps, "tagging_requirement_ids": tagging}


def analyze_repository(
    repo: Dict[str, Any],
    *,
    course_version: Optional[str] = None,
    as_of: Optional[str] = None,
    audience_age: Optional[int] = None,
    blueprint_path: Optional[str] = None,
    blueprint: Optional[Dict[str, Any]] = None,
    low_understanding_threshold: float = 0.6,
) -> Dict[str, Any]:
    if blueprint is None:
        blueprint = load_blueprint(blueprint_path)

    versions = sorted({s.get("course_version", "") for s in rows(repo, "segments") if s.get("course_version")})
    if course_version is None:
        selected_version = versions[-1] if versions else "ALL"
    else:
        selected_version = course_version

    selected = analyze_scope(
        repo,
        selected_version,
        as_of=as_of,
        audience_age=audience_age,
        blueprint=blueprint,
        low_understanding_threshold=low_understanding_threshold,
    )

    # Always retain every version scope.  A recommendation may name an older
    # version even when the printed report selects the current version.
    all_version_reports = {}
    for version in versions:
        all_version_reports[version] = analyze_scope(
            repo,
            version,
            as_of=as_of,
            audience_age=audience_age,
            blueprint=blueprint,
            low_understanding_threshold=low_understanding_threshold,
        )

    issues = validate_repository(repo)
    return {
        "schema_version": 1,
        "tool": "coin-culture-coverage-tool",
        "scope": {"course_version": selected_version, "as_of": as_of, "audience_age": audience_age},
        "available_versions": versions,
        "summary": selected["summary"],
        "report": selected,
        "version_reports": all_version_reports,
        "issues": issues,
        "issue_counts": _count_by([{"level": i["level"]} for i in issues], "level"),
        "repository_snapshot": None,  # CLI/API caller can attach via build_snapshot_report
    }


def analyze_coverage(
    data_dir: str = "data",
    *,
    course_version: Optional[str] = None,
    as_of: Optional[str] = None,
    audience_age: Optional[int] = None,
    blueprint_path: Optional[str] = None,
    recommendations_path: Optional[str] = None,
) -> Dict[str, Any]:
    from .io import load_repository, repository_snapshot

    if blueprint_path is None:
        default_blueprint = Path(__file__).resolve().parent.parent / "config" / "curriculum_blueprint.json"
        if default_blueprint.exists():
            blueprint_path = str(default_blueprint)

    repo = load_repository(data_dir)
    result = analyze_repository(
        repo,
        course_version=course_version,
        as_of=as_of,
        audience_age=audience_age,
        blueprint_path=blueprint_path,
    )
    result["repository_snapshot"] = repository_snapshot(repo)
    records = None
    if recommendations_path:
        records = load_recommendation_records(recommendations_path)
    else:
        for table_name in ("adopted_recommendations", "recommendations"):
            raw_records = rows(repo, table_name)
            if raw_records:
                records = raw_records
                break
    if records is not None:
        from .recommendations import evaluate_recommendations

        result["recommendations"] = evaluate_recommendations(records, result)
    return result
