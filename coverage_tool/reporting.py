"""Markdown reporting for teaching staff and collections staff."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

COVERAGE_LABELS = {
    "strong_coverage": "覆盖且证据强",
    "covered": "覆盖/证据充分",
    "explanation_depth_gap": "有材料但缺深度解释",
    "evidence_gap": "有讲述但证据缺口",
    "evidence_limited": "证据有限/待核",
    "needs_depth_and_evidence": "深度与证据均需加强",
    "annotation_gap": "有反馈但缺主题标注",
    "gap": "缺口",
    "optional_not_scheduled": "非必需且未安排",
}

EVIDENCE_LABELS = {
    "strong": "强（多源）",
    "moderate": "中等（可支持）",
    "provisional": "暂定（待审核）",
    "weak": "弱",
    "unrated": "未评级",
    "none": "无直接证据",
    "lapsed_or_withdrawn": "已失效/撤下",
}

TEACHING_LABELS = {
    "explained": "有解释/分析关系",
    "introduced_or_illustrated_only": "仅介绍、背景或例证",
    "tagged_relation_unclassified": "已标注但关系类型未分类",
    "feedback_only_topic_without_segment_topic": "仅反馈可见，缺主题标注",
    "absent": "未安排",
}


def pct(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def coverage_label(value: str) -> str:
    return COVERAGE_LABELS.get(value, value)


def evidence_label(value: str) -> str:
    return EVIDENCE_LABELS.get(value, value)


def age_label(value: str) -> str:
    return {
        "fit": "适配",
        "restricted": "低于建议年龄",
        "unrated": "未分级",
        "age_rating_known_audience_unknown": "有分级/未提供听众年龄",
        "unknown": "未知",
    }.get(value, value)


def _table(headers: List[str], rows: List[List[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        escaped = [str(cell).replace("\n", "<br>").replace("|", "\\|") for cell in row]
        lines.append("| " + " | ".join(escaped) + " |")
    return "\n".join(lines)


def render_markdown(analysis: Dict[str, Any]) -> str:
    report = analysis.get("report", analysis)
    scope = analysis.get("scope", report.get("scope", {}))
    summary = report.get("summary", {})
    lines: List[str] = []

    lines.append("# 钱币文化课程内容覆盖分析")
    lines.append("")
    lines.append(
        f"- 讲述版本：**{scope.get('course_version', 'ALL')}**；观察日：**{scope.get('as_of') or '未指定（保留全部有效期记录）'}**"
    )
    lines.append(f"- 听众年龄：{scope.get('audience_age') or '未提供；只显示材料年龄分级，不判定是否适配'}")
    lines.append(f"- 段落数：{summary.get('segment_count', 0)}；总时长：{summary.get('total_duration_min', 0)} 分钟（多主题段落不按时长重复分配）")
    lines.append(f"- 必需主题：{summary.get('required_topic_count', 0)}")
    rates = summary.get("required_topic_rates", {})
    if rates:
        lines.append(
            "- 必需主题比率（非段落数）："
            f"已安排 {pct(rates.get('scheduled'))}；"
            f"有解释深度 {pct(rates.get('explanatory_depth'))}；"
            f"证据充分 {pct(rates.get('evidence_sufficient'))}；"
            f"完整覆盖 {pct(rates.get('complete_coverage'))}"
        )
    if analysis.get("generated_at"):
        lines.append(f"- 生成时间：{analysis['generated_at']}")
    lines.append("")

    lines.append("## 1. 结论摘要")
    lines.append("")
    counts = summary.get("coverage_class_counts", {})
    if counts:
        lines.append(_table(["覆盖结论", "主题数"], [[coverage_label(k), v] for k, v in counts.items()]))
        lines.append("")
    if summary.get("gap_topics"):
        lines.append(f"- **必需主题缺口**：{', '.join(summary['gap_topics'])}")
    if summary.get("depth_gap_topics"):
        lines.append(f"- **缺解释深度**：{', '.join(summary['depth_gap_topics'])}")
    if summary.get("provisional_topics"):
        lines.append(f"- **证据仍待审核**：{', '.join(summary['provisional_topics'])}")
    if summary.get("evidence_gap_topics"):
        lines.append(f"- **证据缺口/失效**：{', '.join(summary['evidence_gap_topics'])}")
    if summary.get("low_understanding_topics"):
        lines.append(f"- **低理解率反馈主题**：{', '.join(summary['low_understanding_topics'])}（仅教学信号）")
    if summary.get("age_restricted_used_source_ids"):
        lines.append(f"- **低于材料建议年龄的引用**：{', '.join(summary['age_restricted_used_source_ids'])}；需教师改写或替换材料。")
    if summary.get("orphan_feedback_count"):
        lines.append(f"- 有 {summary['orphan_feedback_count']} 条反馈引用当前 segments 表中不存在的旧段落 ID；已保留为历史反馈，未改挂新段落。")
    if summary.get("out_of_version_feedback_count"):
        lines.append(f"- 另有 {summary['out_of_version_feedback_count']} 条反馈属于其他课程版本；已留在对应版本追溯，未混入本版比率。")
    lines.append("")

    issues = analysis.get("issues", [])
    if issues:
        errors = [i for i in issues if i.get("level") == "error"]
        warnings = [i for i in issues if i.get("level") == "warning"]
        lines.append(f"### 输入核查：{len(errors)} 个错误，{len(warnings)} 个警告")
        for issue in issues[:20]:
            lines.append(f"- `{issue.get('code')}` {issue.get('message')}")
        if len(issues) > 20:
            lines.append(f"- …另有 {len(issues) - 20} 条，见 JSON 报告。")
        lines.append("")

    lines.append("## 2. 主题覆盖矩阵")
    lines.append("")
    rows = []
    for topic in report.get("topics", []):
        fb = topic.get("feedback_summary", {})
        fb_text = f"{pct(fb.get('aggregate_understanding_rate'))} / n={fb.get('respondent_count', 0)}" if fb.get("response_rows") else "无反馈"
        rows.append(
            [
                topic["topic_id"],
                topic["label"],
                topic.get("period", ""),
                "必需" if topic.get("required") else "可选",
                coverage_label(topic["coverage_class"]),
                TEACHING_LABELS.get(topic["teaching_status"], topic["teaching_status"]),
                evidence_label(topic["evidence"]["level"]),
                topic["evidence"].get("independent_source_count", 0),
                fb_text,
            ]
        )
    lines.append(_table(["ID", "主题", "时期", "要求", "覆盖", "讲述深度", "证据", "独立来源", "反馈理解率"], rows))
    lines.append("")
    lines.append("> 段落数只用于定位，不参与“覆盖充分”判定；充分性来自主题关系、解释深度和可追溯证据。")
    lines.append("")

    lines.append("## 3. 讲述顺序、重复与待补主题")
    lines.append("")
    seg_rows = []
    for seg in report.get("segments", []):
        topic_text = ", ".join(f"{link['topic_id']}:{link['relation']}" for link in seg.get("topic_links", []))
        fb_rates = ", ".join(f"{fb['session_id']} {pct(fb['understanding_rate'])}" for fb in seg.get("feedback", []))
        era = (seg.get("era") or {}).get("era", "")
        seg_rows.append([seg.get("position"), seg["segment_id"], seg.get("course_version"), seg.get("duration_min"), era, seg.get("title"), topic_text, fb_rates])
    lines.append(_table(["序", "段落", "版本", "分钟", "推断年代", "标题", "主题/关系", "反馈"], seg_rows))
    lines.append("")
    seq = report.get("sequence_findings", [])
    if seq:
        for item in seq:
            lines.append(f"- **{item.get('code')}**：{item.get('message')}")
    else:
        lines.append("- 未发现重复 position、年代回跳或多段浅层重复规则命中。")
    lineage = report.get("lineage", [])
    if lineage:
        lines.append("- 段落谱系（仅作追溯，不自动迁移反馈）：")
        for edge in lineage:
            lines.append(f"  - `{edge.get('old_segment_id')}` → `{edge.get('new_segment_id')}`（{edge.get('relation_type')}）{edge.get('note', '')}")
    lines.append("")

    arc = report.get("curriculum_arc", {})
    if arc.get("requirements"):
        lines.append("### 连续课程脉络核查")
        lines.append("")
        arc_rows = []
        for req in arc["requirements"]:
            explicit = ", ".join(t["topic_id"] for t in req.get("explicit_topics", [])) or "—"
            hits = ", ".join(f"{h['segment_id']}:{'/'.join(h['matched_keywords'])}" for h in req.get("keyword_hits", [])) or "—"
            status = {
                "explicitly_scheduled_with_text_signal": "明确标注且有文本信号",
                "explicit_broad_topic_verify_specifics": "有宽泛主题，需核实具体点",
                "explicitly_scheduled": "已有明确主题标注",
                "keyword_signal_requires_topic_tag": "有关键词，需补主题标注",
                "gap": "缺口",
            }.get(req["status"], req["status"])
            arc_rows.append([req["label"], req.get("era", ""), status, explicit, hits])
        lines.append(_table(["课程脉络", "年代", "状态", "主题ID", "文本信号"], arc_rows))
        lines.append("")

    actions: List[str] = []
    for topic in report.get("topics", []):
        if not topic.get("required"):
            continue
        if topic["coverage_class"] == "gap":
            actions.append(f"**补主题/段落**：{topic['topic_id']}《{topic['label']}》尚无段落标注，应先确定讲述目标，再补段落、时长和材料。")
        if not topic.get("has_explanatory_relation") and topic.get("teaching_status") != "absent":
            actions.append(f"**补解释链**：{topic['topic_id']}《{topic['label']}》仅有浅层关系，应明确货币、信用与地方经济之间的因果或比较。")
        if topic["evidence"]["level"] in {"none", "lapsed_or_withdrawn"}:
            actions.append(f"**补证据/馆藏复核**：{topic['topic_id']}《{topic['label']}》缺少当前可用的直接来源。")
        elif topic["evidence"]["level"] == "provisional":
            actions.append(f"**推进来源审核**：{topic['topic_id']}《{topic['label']}》目前仅有 review/待核来源，结论应标为暂定。")
        for fb in topic.get("feedback", []):
            if fb.get("low_understanding"):
                actions.append(f"**教学法调整**：{fb['session_id']}/{fb['segment_id']} 的 {topic['topic_id']} 理解率为 {pct(fb['understanding_rate'])}，可增加图示、类比或前后测，但这不证明史料可靠。")
    for req in arc.get("requirements", []):
        if req.get("status") == "gap" and req.get("required") and req.get("advice"):
            actions.append(f"**补连续课程脉络**：{req['label']}。{req['advice']}")
        elif req.get("status") == "keyword_signal_requires_topic_tag" and req.get("advice"):
            actions.append(f"**补主题标注**：{req['label']}已在文本中出现但未规范标注。{req['advice']}")
    unmapped = report.get("source_collection", {}).get("unmapped_claims", [])
    for claim in unmapped:
        actions.append(f"**馆藏范围确认**：`{claim['reference_id']}` 的“{claim['claim_topic']}”未精确匹配主题表，需确认来源是否支持该叙述或改写 claim。")
    if actions:
        lines.append("### 可执行修订建议")
        lines.append("")
        for action in dict.fromkeys(actions):
            lines.append(f"- {action}")
        lines.append("")

    lines.append("## 4. 主题结论的材料与版本追溯")
    lines.append("")
    for topic in report.get("topics", []):
        lines.append(f"### {topic['topic_id']} {topic['label']} — {coverage_label(topic['coverage_class'])}")
        lines.append("")
        lines.append(f"- 结论：{coverage_label(topic['coverage_class'])}；讲述状态：{TEACHING_LABELS.get(topic['teaching_status'], topic['teaching_status'])}；证据：{evidence_label(topic['evidence']['level'])}。")
        if topic.get("findings"):
            for finding in topic["findings"]:
                lines.append(f"- 研判：{finding}")
        if topic.get("segments"):
            chain = []
            for seg_ref in topic["segments"]:
                validity = f"{seg_ref.get('valid_from') or '?'}→{seg_ref.get('valid_to') or '开放'}"
                chain.append(f"{seg_ref['segment_id']}({seg_ref.get('relation')}, {validity})")
            lines.append(f"- 段落/关系链：{'; '.join(chain)}")
        if topic.get("references"):
            for ref in topic["references"]:
                source = ref.get("source", {})
                lines.append(
                    f"- 证据链：`{ref['reference_id']}` / {ref['segment_id']} → `{ref['source_id']}` "
                    f"（{source.get('object_token', '')}；{source.get('source_note', '')}；"
                    f"状态原值=`{source.get('review_status_raw', '')}`；可信层={source.get('trust_tier')}；"
                    f"可用性={source.get('availability_state')}；年龄={age_label(source.get('age', {}).get('status', ''))}）"
                )
        else:
            lines.append("- 证据链：无精确映射的 reference；馆藏人员不应把近似 claim_topic 自动视作本主题证据。")
        if topic.get("feedback"):
            for fb in topic["feedback"]:
                interval = fb.get("wilson_95")
                interval_text = f"，95%区间 {pct(interval[0])}–{pct(interval[1])}" if interval else ""
                session_date = f"，场次日期 {fb['session_date']}" if fb.get("session_date") else ""
                session_relation = ""
                active_relations = fb.get("active_relation_on_session") or []
                if active_relations:
                    session_relation = "；当日关系=" + "/".join(r.get("relation", "") for r in active_relations)
                lines.append(
                    f"- 旧反馈：{fb['session_id']} / {fb['segment_id']} / {fb['topic_id']} "
                    f"{fb['understood_count']}/{fb['respondent_count']} = {pct(fb['understanding_rate'])}{interval_text}{session_date}{session_relation}；"
                    "仅追溯当时理解反馈。"
                )
        for fb in topic.get("historical_feedback", []):
            lineage = ""
            if fb.get("lineage_descendants"):
                successors = ", ".join(edge.get("new_segment_id", "") for edge in fb["lineage_descendants"])
                lineage = f"；谱系提示可参考新段 {successors}，但反馈不自动改挂"
            lines.append(
                f"- 已退役段落的历史反馈：{fb['session_id']} / 旧段 `{fb['segment_id']}` / {fb['topic_id']} "
                f"{fb['understood_count']}/{fb['respondent_count']} = {pct(fb['understanding_rate'])}；"
                f"按旧 segment_id 保留{lineage}。"
            )
        lines.append("")

    lines.append("## 5. 馆藏与图像核查")
    lines.append("")
    collection = report.get("source_collection", {})
    source_rows = []
    for source in collection.get("sources", []):
        source_rows.append(
            [
                source["source_id"],
                source.get("object_token", ""),
                source.get("review_status_raw", ""),
                source.get("trust_tier", ""),
                source.get("availability_state", ""),
                age_label(source.get("age", {}).get("status", "")),
                "是" if source.get("used_in_scope") else "否",
                source.get("reference_count_in_scope", 0),
            ]
        )
    lines.append(_table(["来源", "馆藏/图像 token", "review_status 原值", "可信层", "可用性", "年龄适配", "本版引用", "引用数"], source_rows))
    lines.append("")
    if collection.get("unmapped_claims"):
        lines.append("### 超出精确主题映射或需来源范围复核的叙述")
        for claim in collection["unmapped_claims"]:
            lines.append(f"- `{claim['reference_id']}`（{claim['segment_id']}）claim_topic=“{claim['claim_topic']}” 未精确匹配 topics 表。")
        lines.append("")
    if collection.get("unused_available_source_ids"):
        lines.append(f"- 可用但本版未引用：{', '.join(collection['unused_available_source_ids'])}")
    if collection.get("age_unknown_source_ids"):
        lines.append(f"- 缺适合年龄记录：{', '.join(collection['age_unknown_source_ids'])}；需馆藏/教研补 profile，不能默认全年龄。")
    lines.append("")

    section_no = 6
    rec_result = analysis.get("recommendations")
    if rec_result:
        lines.append(f"## {section_no}. 已采用教学建议复核")
        section_no += 1
        lines.append("")
        lines.append(f"共 {rec_result['summary'].get('total', 0)} 条；需复核：{', '.join(rec_result['summary'].get('review_required', [])) or '无'}。")
        lines.append("")
        if rec_result.get("records"):
            rec_rows = []
            for rec in rec_result["records"]:
                changes = "; ".join(c.get("type", "") for c in rec.get("change_findings", [])) or "—"
                rec_rows.append([
                    rec["recommendation_id"],
                    rec.get("course_version", ""),
                    rec.get("topic_id", ""),
                    rec.get("disposition", ""),
                    changes,
                    rec.get("topic_coverage_class_now", ""),
                    "是" if rec.get("topic_still_evidence_supported") else "否",
                ])
            lines.append(_table(["建议ID", "版本", "主题", "处置", "变化", "当前覆盖", "剩余证据充分"], rec_rows))
            lines.append("")

    if analysis.get("version_reports"):
        lines.append(f"## {section_no}. 版本对比索引")
        section_no += 1
        lines.append("")
        version_rows = []
        for version, vr in analysis["version_reports"].items():
            version_rows.append([
                version,
                vr["summary"].get("segment_count"),
                vr["summary"].get("total_duration_min"),
                ", ".join(vr["summary"].get("gap_topics", [])) or "—",
                ", ".join(vr["summary"].get("evidence_gap_topics", [])) or "—",
            ])
        lines.append(_table(["版本", "段落", "时长", "必需缺口", "证据风险主题"], version_rows))
        lines.append("")

    snap = analysis.get("repository_snapshot") or {}
    hashes = snap.get("file_hashes") or analysis.get("input_hashes") or {}
    if hashes:
        lines.append(f"## {section_no}. 输入指纹")
        section_no += 1
        lines.append("")
        for filename, digest in sorted(hashes.items()):
            lines.append(f"- `{filename}`: `{digest}`")
        lines.append("")

    lines.append("## 方法边界")
    lines.append("")
    for note in report.get("method_notes", []):
        lines.append(f"- {note}")
    lines.append("- 本工具不生成历史事实结论；它整理讲稿标注、来源支持范围和可复核线索，最终叙述需教研与馆藏人员确认。")
    lines.append("")
    return "\n".join(lines)


def render_impact_markdown(impact: Dict[str, Any]) -> str:
    lines = ["# 课程修订影响分析", ""]
    lines.append(f"- 观察日：{impact.get('as_of') or '未指定'}")
    lines.append(f"- 新段落：{', '.join(impact.get('new_segment_ids_auto_included', [])) or '无'}")
    lines.append(f"- 删除段落：{', '.join(impact.get('removed_segment_ids', [])) or '无'}")
    lines.append("")

    lines.append("## 来源变化")
    lines.append("")
    if impact.get("source_changes"):
        rows = []
        for change in impact["source_changes"]:
            rows.append([
                change["source_id"],
                change["change_type"],
                ", ".join(change.get("changed_fields", [])) or "—",
                (change.get("after") or {}).get("review_status", (change.get("before") or {}).get("review_status", "")),
            ])
        lines.append(_table(["来源", "变化类型", "字段", "审核状态值"], rows))
    else:
        lines.append("未检测到 sources.csv 变化。")
    lines.append("")

    lines.append("## 受影响主题覆盖")
    lines.append("")
    if impact.get("affected_topics"):
        rows = []
        for item in impact["affected_topics"]:
            rows.append([
                item.get("course_version"),
                item.get("topic_id"),
                coverage_label(item.get("coverage_before") or ""),
                coverage_label(item.get("coverage_after") or ""),
                evidence_label(item.get("evidence_before") or ""),
                evidence_label(item.get("evidence_after") or ""),
                item.get("remaining_independent_source_count"),
                "是" if item.get("other_evidence_sufficient") else "否",
                item.get("impact_label"),
            ])
        lines.append(_table(["版本", "主题", "覆盖前", "覆盖后", "证据前", "证据后", "剩余独立源", "其他证据充分", "影响判定"], rows))
        lines.append("")
        for item in impact["affected_topics"]:
            lines.append(
                f"- `{item['topic_id']}`/{item['course_version']}：引用 {', '.join(item['reference_ids'])} / 来源 {', '.join(item['source_ids'])}；"
                f"剩余来源 {', '.join(item['remaining_source_ids']) or '无'}。{item['impact_label']}。"
            )
    else:
        lines.append("没有引用这些变化来源的主题。")
    lines.append("")

    rec = impact.get("recommendations")
    if rec:
        lines.append("## 已采用教学建议")
        lines.append("")
        lines.append(f"需复核：{', '.join(rec['summary'].get('review_required', [])) or '无'}")
        for item in rec.get("records", []):
            if item.get("review_required"):
                changes = "; ".join(c.get("type", "") for c in item.get("change_findings", []))
                lines.append(f"- `{item['recommendation_id']}` → {item['disposition']}；变化：{changes}")
        lines.append("")

    lines.append("## 结构表变化")
    lines.append("")
    for filename, change in impact.get("table_changes", {}).items():
        if change.get("added") or change.get("removed") or change.get("changed"):
            lines.append(f"### {filename}")
            lines.append(f"- 新增：{', '.join(change.get('added', [])) or '无'}")
            lines.append(f"- 删除：{', '.join(change.get('removed', [])) or '无'}")
            lines.append(f"- 修改：{', '.join(c['id'] for c in change.get('changed', [])) or '无'}")
    lines.append("")
    for note in impact.get("explanation", []):
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def write_report_files(output_dir: str, analysis: Dict[str, Any], basename: str = "coverage-report") -> Dict[str, str]:
    from pathlib import Path

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{basename}.json"
    md_path = out / f"{basename}.md"
    json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(analysis), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}
