"""Configurable relation, trust and chronology classifications."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

RELATION_CLASSES = {
    "explanatory": {
        "rank": 3,
        "labels": ("解释", "分析", "因果", "联系", "比较", "论证"),
        "markers": (
            "explain",
            "explains",
            "explanation",
            "analy",
            "cause",
            "causal",
            "effect",
            "connect",
            "connection",
            "relationship",
            "relation",
            "compare",
            "comparison",
            "why",
            "mechanism",
        ),
    },
    "descriptive": {
        "rank": 1,
        "labels": ("描述", "外观", "外形", "形制描述"),
        "markers": (
            "describe",
            "describes",
            "description",
            "appearance",
            "shape",
            "look",
            "visual",
            "form_description",
        ),
    },
    "illustrative": {
        "rank": 1,
        "labels": ("例子", "例证", "示例", "图像"),
        "markers": ("example", "illustrate", "illustrates", "illustration", "case", "image"),
    },
    "contextual": {
        "rank": 1,
        "labels": ("背景", "语境", "上下文"),
        "markers": ("context", "background", "setting"),
    },
    "introductory": {
        "rank": 1,
        "labels": ("引入", "介绍", "概述"),
        "markers": ("introduce", "introduces", "introduction", "overview", "survey"),
    },
}

BLOCKED_STATUSES = {
    "retracted",
    "withdrawn",
    "removed",
    "rejected",
    "deleted",
    "unavailable",
    "撤下",
    "撤回",
    "撤销",
    "驳回",
    "失效",
    "已撤",
}

HIGH_TRUST_STATUSES = {
    "approved",
    "verified",
    "authoritative",
    "confirmed",
    "审核通过",
    "已审核",
    "通过",
    "已核实",
}

MEDIUM_TRUST_STATUSES = {
    "corroborated",
    "edited",
    "corrected",
    "已更正",
    "已校订",
}

PROVISIONAL_STATUSES = {
    "review",
    "pending",
    "under_review",
    "in_review",
    "draft",
    "submitted",
    "待审核",
    "审核中",
    "待核实",
    "草稿",
}


def classify_relation(relation: str) -> Dict[str, Any]:
    raw = relation or ""
    text = raw.strip().lower().replace("-", "_").replace(" ", "_")
    if not text:
        return {"raw": raw, "class": "empty", "depth_rank": 0, "explanatory": False}

    for class_name, spec in RELATION_CLASSES.items():
        if text in spec["markers"] or text == class_name:
            return {
                "raw": raw,
                "class": class_name,
                "depth_rank": spec["rank"],
                "explanatory": class_name == "explanatory",
            }
        if any(marker in text for marker in spec["markers"]):
            return {
                "raw": raw,
                "class": class_name,
                "depth_rank": spec["rank"],
                "explanatory": class_name == "explanatory",
            }
        if any(label in raw for label in spec["labels"]):
            return {
                "raw": raw,
                "class": class_name,
                "depth_rank": spec["rank"],
                "explanatory": class_name == "explanatory",
            }

    return {"raw": raw, "class": "unclassified", "depth_rank": None, "explanatory": False}


def normalise_trust_tier(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"high", "strong", "tier1", "1", "高", "一级", "可信"}:
        return "high"
    if text in {"medium", "moderate", "tier2", "2", "中", "二级"}:
        return "medium"
    if text in {"low", "weak", "tier3", "3", "低", "三级"}:
        return "low"
    if text in {"provisional", "review", "unverified", "待核", "待审核"}:
        return "provisional"
    return text


def status_trust(review_status: str) -> str:
    status = (review_status or "").strip().lower()
    if status in BLOCKED_STATUSES:
        return "blocked"
    if status in HIGH_TRUST_STATUSES:
        return "high"
    if status in MEDIUM_TRUST_STATUSES:
        return "medium"
    if status in PROVISIONAL_STATUSES:
        return "provisional"
    if not status:
        return "empty_status"
    return "unrated_status"


def parse_age_rating(*values: Optional[str]) -> Optional[int]:
    """Extract a minimum age from values such as ``12`` or ``12+``."""
    for value in values:
        if value is None:
            continue
        text = str(value).strip().lower()
        if not text:
            continue
        if text in {"all", "general", "universal", "all ages", "普遍", "全年齡", "全年龄", "不限"}:
            return 0
        digits = ""
        for char in text:
            if char.isdigit():
                digits += char
            elif digits:
                break
        if digits:
            return int(digits)
    return None


def load_blueprint(path: Optional[str | Path]) -> Dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def infer_era(text: str, blueprint: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    rules = (blueprint or {}).get("chronology", [])
    haystack = (text or "").lower()
    matches = []
    for rule in rules:
        keywords = rule.get("keywords", [])
        hit = [word for word in keywords if str(word).lower() in haystack]
        if hit:
            matches.append(
                {
                    "era": rule.get("era"),
                    "order": rule.get("order"),
                    "matched_keywords": hit,
                }
            )
    if not matches:
        return None
    # Prefer the earliest explicit era when several keywords occur.
    return sorted(matches, key=lambda item: item.get("order", 999))[0]
