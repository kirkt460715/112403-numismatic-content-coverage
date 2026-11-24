import csv
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from input_audit import inspect_inputs

from coverage_tool.analyzer import analyze_coverage, analyze_repository
from coverage_tool.cli import main
from coverage_tool.io import load_repository
from coverage_tool.impact import compare_revisions
from coverage_tool.recommendations import recommendation_from_findings

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BLUEPRINT = ROOT / "config" / "curriculum_blueprint.json"
AS_OF = "2026-11-24"


class CoverageToolTests(unittest.TestCase):
    def test_input_contract_and_composite_keys(self):
        counts = inspect_inputs(DATA)
        self.assertEqual(counts["segments.csv"], 5)
        self.assertEqual(counts["topics.csv"], 4)
        self.assertGreaterEqual(counts["segment_topics.csv"], 5)

    def test_c2_coverage_distinguishes_gap_depth_and_provisional_evidence(self):
        result = analyze_coverage(
            DATA,
            course_version="C2",
            as_of=AS_OF,
            audience_age=12,
            blueprint_path=str(BLUEPRINT),
        )
        topics = {t["topic_id"]: t for t in result["report"]["topics"]}

        self.assertEqual(topics["T1"]["coverage_class"], "explanation_depth_gap")
        self.assertEqual(topics["T1"]["evidence"]["level"], "moderate")
        self.assertFalse(topics["T1"]["has_explanatory_relation"])

        self.assertEqual(topics["T2"]["coverage_class"], "gap")
        self.assertEqual(topics["T3"]["coverage_class"], "gap")

        self.assertEqual(topics["T4"]["teaching_status"], "explained")
        self.assertEqual(topics["T4"]["evidence"]["level"], "provisional")
        self.assertTrue(topics["T4"]["feedback"][0]["low_understanding"])
        self.assertLess(topics["T4"]["feedback"][0]["understanding_rate"], 0.6)

        # Feedback heat/comprehension does not upgrade provisional evidence.
        self.assertFalse(topics["T4"]["evidence"]["sufficient"])

        chain_refs = topics["T4"]["references"]
        self.assertEqual([r["reference_id"] for r in chain_refs], ["L5"])
        self.assertEqual(chain_refs[0]["source_id"], "A2")
        self.assertEqual(chain_refs[0]["source"]["review_status_raw"], "review")

        arc = {r["requirement_id"]: r["status"] for r in result["report"]["curriculum_arc"]["requirements"]}
        self.assertEqual(arc["tang_tongbao"], "gap")
        self.assertEqual(arc["song_jiaozi"], "gap")
        self.assertEqual(arc["pre_qin_cowrie"], "gap")

    def test_c1_scope_mismatch_and_chronology_regression_are_explained(self):
        result = analyze_coverage(
            DATA,
            course_version="C1",
            as_of="2026-09-15",
            blueprint_path=str(BLUEPRINT),
        )
        report = result["report"]
        topics = {t["topic_id"]: t for t in report["topics"]}

        self.assertEqual(topics["T3"]["coverage_class"], "evidence_gap")
        self.assertEqual(topics["T3"]["evidence"]["level"], "none")
        self.assertEqual(topics["T3"]["references"], [])
        unmapped = report["source_collection"]["unmapped_claims"]
        self.assertTrue(any(item["reference_id"] == "L3" and item["claim_topic"] == "地方货币" for item in unmapped))

        codes = {item["code"] for item in report["sequence_findings"]}
        self.assertIn("chronology_regression", codes)

        t3_feedback = topics["T3"]["feedback"][0]
        self.assertEqual(t3_feedback["session_id"], "S1")
        self.assertEqual(t3_feedback["segment_id"], "G03")
        self.assertEqual(t3_feedback["understanding_rate"], 0.75)

    def test_new_segment_is_auto_included_and_historical_feedback_not_reattributed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_dir = tmp_path / "data"
            shutil.copytree(DATA, data_dir)

            with (data_dir / "segments.csv").open("a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["G06", "C3", 1, 6, "战国尖足布分型"])

            with (data_dir / "segment_topics.csv").open("a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["G06", "T3", "explains", AS_OF, ""])

            # Simulate an old segment row being retired after a split while
            # old feedback still names the stable historical ID G03.
            segments_path = data_dir / "segments.csv"
            with segments_path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            fields = list(rows[0].keys())
            rows = [r for r in rows if r["segment_id"] != "G03"]
            with segments_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)

            with (data_dir / "segment_lineage.csv").open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["old_segment_id", "new_segment_id", "relation_type", "note"])
                writer.writerow(["G03", "G06", "split", "尖足布部分拆入新段"])

            result = analyze_coverage(data_dir, course_version="C3", as_of=AS_OF)
            report = result["report"]
            self.assertEqual([s["segment_id"] for s in report["segments"]], ["G06"])
            t3 = next(t for t in report["topics"] if t["topic_id"] == "T3")
            self.assertTrue(t3["has_explanatory_relation"])
            self.assertEqual(t3["feedback"], [])

            orphan_ids = [fb["segment_id"] for fb in report["orphan_feedback"]]
            self.assertIn("G03", orphan_ids)
            g03_fb = next(fb for fb in report["orphan_feedback"] if fb["segment_id"] == "G03")
            self.assertEqual(g03_fb["attribution_policy"], "retain_missing_historical_segment_id")
            self.assertEqual(g03_fb["lineage_descendants"][0]["new_segment_id"], "G06")

            all_result = analyze_coverage(data_dir, course_version="ALL", as_of=AS_OF)
            all_t3 = next(t for t in all_result["report"]["topics"] if t["topic_id"] == "T3")
            self.assertTrue(any(fb["segment_id"] == "G03" for fb in all_t3["historical_feedback"]))
            self.assertFalse(any(fb["segment_id"] == "G06" for fb in all_t3["feedback"]))

    def test_source_withdrawal_keeps_topic_when_other_independent_evidence_remains(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_dir = tmp_path / "data"
            shutil.copytree(DATA, data_dir)

            with (data_dir / "sources.csv").open("a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["A4", "COIN04", "独立权威档案", "approved", "2026-08-01", ""])
            with (data_dir / "references.csv").open("a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["L6", "G05", "A4", "票号信用", "C2"])

            baseline = analyze_coverage(data_dir, as_of=AS_OF)
            recommendation = recommendation_from_findings(
                "R-IMPACT",
                "补充票号信用的两种独立证据",
                baseline,
                topic_id="T4",
                segment_id="G05",
                course_version="C2",
                reference_ids=["L5", "L6"],
                adopted_at="2026-11-20",
            )

            sources_path = data_dir / "sources.csv"
            text = sources_path.read_text(encoding="utf-8")
            text = text.replace(
                "A2,COIN02,地方史料摘录,review,2026-08-01,",
                "A2,COIN02,地方史料摘录,retracted,2026-08-01,2026-11-01",
            )
            sources_path.write_text(text, encoding="utf-8")

            current_repo = load_repository(data_dir)
            impact = compare_revisions(
                baseline,
                current_repo,
                as_of=AS_OF,
                recommendation_records=[recommendation],
            )
            t4 = next(item for item in impact["affected_topics"] if item["topic_id"] == "T4" and item["course_version"] == "C2")
            self.assertIn("A4", t4["remaining_source_ids"])
            self.assertTrue(t4["other_evidence_sufficient"])
            self.assertEqual(t4["coverage_after"], "covered")

            rec = impact["recommendations"]["records"][0]
            self.assertTrue(rec["review_required"])
            self.assertEqual(rec["disposition"], "affected_needs_revalidation_coverage_retained")
            self.assertTrue(rec["topic_still_evidence_supported"])

    def test_source_note_correction_requires_advice_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_dir = tmp_path / "data"
            shutil.copytree(DATA, data_dir)
            baseline = analyze_coverage(data_dir, as_of=AS_OF)
            rec = recommendation_from_findings(
                "R-NOTE",
                "使用地方史料支持票号解释",
                baseline,
                topic_id="T4",
                course_version="C2",
                reference_ids=["L5"],
            )

            sources_path = data_dir / "sources.csv"
            text = sources_path.read_text(encoding="utf-8").replace("地方史料摘录", "地方史料摘录（更正版）")
            sources_path.write_text(text, encoding="utf-8")

            impact = compare_revisions(baseline, load_repository(data_dir), as_of=AS_OF, recommendation_records=[rec])
            source_change = next(c for c in impact["source_changes"] if c["source_id"] == "A2")
            self.assertEqual(source_change["change_type"], "source_note_corrected")
            evaluated = impact["recommendations"]["records"][0]
            self.assertTrue(any(c["type"] == "source_note_corrected" for c in evaluated["change_findings"]))
            self.assertTrue(evaluated["review_required"])

    def test_undated_analysis_does_not_treat_open_source_as_withdrawn(self):
        result = analyze_coverage(DATA, course_version="C2")
        t1 = next(t for t in result["report"]["topics"] if t["topic_id"] == "T1")
        self.assertEqual(t1["evidence"]["level"], "moderate")
        self.assertTrue(t1["evidence"]["sufficient"])

    def test_session_date_selects_relation_active_when_feedback_was_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            shutil.copytree(DATA, data_dir)
            (data_dir / "sessions.csv").write_text(
                "session_id,session_date,course_version\nS1,2026-09-10,C1\n",
                encoding="utf-8",
            )
            result = analyze_coverage(data_dir, course_version="C1", as_of="2026-11-24")
            t3 = next(t for t in result["report"]["topics"] if t["topic_id"] == "T3")
            fb = t3["feedback"][0]
            self.assertEqual(fb["session_date"], "2026-09-10")
            self.assertEqual([r["relation"] for r in fb["active_relation_on_session"]], ["example"])

    def test_age_profile_is_separate_from_historical_trust(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            shutil.copytree(DATA, data_dir)
            (data_dir / "source_profiles.csv").write_text(
                "source_id,trust_tier,min_age,handling_note\nA1,high,16,需要教师引导\n",
                encoding="utf-8",
            )
            result = analyze_coverage(data_dir, course_version="C2", as_of=AS_OF, audience_age=12)
            a1 = next(s for s in result["report"]["source_collection"]["sources"] if s["source_id"] == "A1")
            self.assertEqual(a1["age"]["status"], "restricted")
            self.assertFalse(a1["age"]["age_fit"])
            t1 = next(t for t in result["report"]["topics"] if t["topic_id"] == "T1")
            self.assertTrue(t1["evidence"]["sufficient"])

    def test_cli_analyze_writes_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "reports"
            with redirect_stdout(io.StringIO()):
                code = main([
                    "analyze",
                    "--data", str(DATA),
                    "--as-of", AS_OF,
                    "--out", str(out),
                    "--blueprint", str(BLUEPRINT),
                ])
            self.assertEqual(code, 0)
            self.assertTrue((out / "coverage-report.json").exists())
            self.assertTrue((out / "coverage-report.md").exists())
            payload = json.loads((out / "coverage-report.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)
            self.assertIn("repository_snapshot", payload)


if __name__ == "__main__":
    unittest.main()
