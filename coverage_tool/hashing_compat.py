"""Stable hashing helpers for provenance and correction detection."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def note_hash(source_row: Dict[str, Any]) -> str:
    return sha256_text(str(source_row.get("source_note", "")))


def canonical_row_hash(row: Dict[str, Any]) -> str:
    """Hash a row independent of dict insertion order."""
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_text(payload)
