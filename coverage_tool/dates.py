"""Date helpers.

The fixtures use ISO ``YYYY-MM-DD`` values and empty strings for open ranges.
We treat ordinary calendar-date ranges as inclusive on both ends.  Temporal
link tables may alternatively be interpreted as half-open warehouses; callers
that need that convention can pass ``inclusive_end=False``.
"""

from __future__ import annotations

from datetime import date
from typing import Optional, Union

DateValue = Union[date, str, None]


def parse_date(value: DateValue, field: str = "date") -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} must be YYYY-MM-DD, got {value!r}") from exc


def interval_active(
    on_date: Optional[DateValue],
    start: DateValue,
    end: DateValue,
    *,
    inclusive_end: bool = True,
) -> Optional[bool]:
    """Return whether *on_date* is in an interval.

    ``None`` means that no observation date was supplied; callers should treat
    the record as undated rather than automatically active or inactive.
    """
    if on_date is None:
        return None

    target = parse_date(on_date, "as_of")
    start_date = parse_date(start, "valid_from")
    end_date = parse_date(end, "valid_to")
    assert target is not None

    if start_date is not None and target < start_date:
        return False
    if end_date is not None:
        if inclusive_end and target > end_date:
            return False
        if not inclusive_end and target >= end_date:
            return False
    return True
