"""Source availability, trust and age-fit evaluation."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .dates import interval_active
from .taxonomy import normalise_trust_tier, parse_age_rating, status_trust


def evaluate_source(
    source: Dict[str, str],
    *,
    as_of: Optional[str] = None,
    audience_age: Optional[int] = None,
    profile: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    profile = profile or {}
    raw_status = source.get("review_status", "")
    status_class = status_trust(raw_status)

    explicit_trust = normalise_trust_tier(
        source.get("trust_tier") or source.get("credibility") or profile.get("trust_tier")
    )
    trust_tier = explicit_trust or {
        "high": "high",
        "medium": "medium",
        "blocked": "blocked",
        "provisional": "provisional",
    }.get(status_class, "unrated")

    age_min = parse_age_rating(
        source.get("min_age"),
        source.get("age_rating"),
        source.get("minimum_age"),
        profile.get("min_age"),
        profile.get("age_rating"),
    )
    age_fit: Optional[bool]
    if age_min is None:
        age_fit = None
        age_status = "unrated"
    elif audience_age is None:
        age_fit = None
        age_status = "age_rating_known_audience_unknown"
    else:
        age_fit = audience_age >= age_min
        age_status = "fit" if age_fit else "restricted"

    if as_of is None:
        availability_state = "undated_scope"
        available: Optional[bool] = None
    else:
        active = interval_active(as_of, source.get("available_from", ""), source.get("available_to", ""))
        if active is None:
            availability_state = "unknown"
            available = None
        elif active:
            availability_state = "available"
            available = True
        else:
            # Distinguish not-yet from expired for actionable collection review.
            from .dates import parse_date

            target = parse_date(as_of, "as_of")
            start = parse_date(source.get("available_from", ""), "available_from")
            if start and target and target < start:
                availability_state = "not_yet_available"
            else:
                availability_state = "availability_window_closed"
            available = False

    blocked = status_class == "blocked" or trust_tier == "blocked"
    # None means "no date was supplied", not "known unavailable".  Do not turn
    # an undated historical analysis into a false withdrawal result.
    currently_usable = available is not False and not blocked
    return {
        "source_id": source.get("source_id", ""),
        "object_token": source.get("object_token", ""),
        "source_note": source.get("source_note", ""),
        "review_status_raw": raw_status,
        "status_class": status_class,
        "trust_tier": trust_tier,
        "blocked": blocked,
        "availability_state": availability_state,
        "available_on_date": available,
        "currently_usable": currently_usable,
        "age": {
            "minimum_age": age_min,
            "audience_age": audience_age,
            "age_fit": age_fit,
            "status": age_status,
        },
        "profile_note": profile.get("handling_note") or profile.get("age_note") or "",
    }


def evidence_strength(evaluated_sources: list[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate independent sources.

    References to the same source are never counted as corroboration.
    """
    direct = [s for s in evaluated_sources if s.get("claim_alignment") == "direct"]
    by_source: Dict[str, Dict[str, Any]] = {}
    for item in direct:
        by_source.setdefault(item["source_id"], item)
    sources = list(by_source.values())
    usable = [s for s in sources if s.get("currently_usable")]
    high = [s for s in usable if s.get("trust_tier") == "high"]
    medium = [s for s in usable if s.get("trust_tier") == "medium"]
    provisional = [s for s in usable if s.get("trust_tier") == "provisional"]
    low = [s for s in usable if s.get("trust_tier") == "low"]

    if not sources:
        level = "none"
        sufficient = False
        rationale = "没有把 claim_topic 精确对应到该主题的引用。"
    elif not usable:
        level = "lapsed_or_withdrawn"
        sufficient = False
        rationale = "有直接引用，但材料在观察日不可用、被撤下或驳回。"
    elif len(high) >= 2 or (high and medium):
        level = "strong"
        sufficient = True
        rationale = "至少有两个相互独立且可信/已审核的来源。"
    elif len(high) == 1 or len(medium) >= 2:
        level = "moderate"
        sufficient = True
        rationale = "至少有一个已审核高可信来源，或两个中等可信独立来源；可支持结论但宜继续补证。"
    elif provisional:
        level = "provisional"
        sufficient = False
        rationale = "现有直接来源仍处于 review/待核状态，只能作暂定证据。"
    elif low:
        level = "weak"
        sufficient = False
        rationale = "只有低可信来源，不足以单独支持历史解释。"
    else:
        level = "unrated"
        sufficient = False
        rationale = "来源可用但缺少可信等级或审核结论。"

    return {
        "level": level,
        "sufficient": sufficient,
        "independent_source_count": len(sources),
        "usable_source_count": len(usable),
        "high_trust_count": len(high),
        "medium_trust_count": len(medium),
        "provisional_count": len(provisional),
        "source_ids": [s["source_id"] for s in sources],
        "rationale": rationale,
    }
