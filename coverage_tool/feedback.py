"""Feedback statistics.

Feedback is a comprehension/engagement signal only.  It must never be used as
evidence that a historical claim or source interpretation is reliable.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


def wilson_interval(understood: int, respondents: int, z: float = 1.96) -> Optional[tuple[float, float]]:
    if respondents <= 0:
        return None
    p = understood / respondents
    denominator = 1 + z * z / respondents
    centre = (p + z * z / (2 * respondents)) / denominator
    margin = z * math.sqrt(p * (1 - p) / respondents + z * z / (4 * respondents * respondents)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def feedback_record(row: Dict[str, str], low_threshold: float = 0.6) -> Dict[str, Any]:
    try:
        understood = int(row.get("understood_count", "") or 0)
        respondents = int(row.get("respondent_count", "") or 0)
    except ValueError:
        understood, respondents = -1, -1

    valid_counts = understood >= 0 and respondents >= 0 and understood <= respondents
    rate = understood / respondents if valid_counts and respondents else None
    interval = wilson_interval(understood, respondents) if valid_counts else None
    return {
        "session_id": row.get("session_id", ""),
        "segment_id": row.get("segment_id", ""),
        "topic_id": row.get("topic_id", ""),
        "understood_count": understood,
        "respondent_count": respondents,
        "understanding_rate": round(rate, 4) if rate is not None else None,
        "wilson_95": [round(interval[0], 4), round(interval[1], 4)] if interval else None,
        "low_understanding": rate is not None and rate < low_threshold,
        "valid_counts": valid_counts,
        "evidential_role": "comprehension_only_not_historical_reliability",
    }


def summarise_feedback(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_respondents = sum(item["respondent_count"] for item in records if item["valid_counts"])
    total_understood = sum(item["understood_count"] for item in records if item["valid_counts"])
    rate = total_understood / total_respondents if total_respondents else None
    return {
        "response_rows": len(records),
        "respondent_count": total_respondents,
        "understood_count": total_understood,
        "aggregate_understanding_rate": round(rate, 4) if rate is not None else None,
        "low_understanding_rows": [
            f"{item['session_id']}:{item['segment_id']}:{item['topic_id']}"
            for item in records
            if item.get("low_understanding")
        ],
        "warning": "反馈热度和理解率不能证明历史解释或材料来源可靠。",
    }
