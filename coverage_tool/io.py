"""Loading and deterministic snapshots of CSV/JSON course records."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

PathLike = Union[str, Path]

CORE_TABLES = (
    "segments",
    "topics",
    "segment_topics",
    "references",
    "sources",
    "feedback",
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: PathLike) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: PathLike) -> tuple[List[str], List[Dict[str, str]]]:
    path = Path(path)
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = list(reader.fieldnames or [])
        rows: List[Dict[str, str]] = []
        for raw in reader:
            row = {key: ("" if value is None else str(value)) for key, value in raw.items()}
            rows.append(row)
    return columns, rows


def _table_key(filename: str) -> str:
    return filename[:-4] if filename.endswith(".csv") else filename


def load_repository(data_dir: PathLike = "data") -> Dict[str, Any]:
    """Load the manifest-declared tables and any recognised optional tables."""
    root = Path(data_dir)
    manifest_path = root / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else {"tables": [{"file": f"{name}.csv"} for name in CORE_TABLES]}
    )

    tables: Dict[str, Dict[str, Any]] = {}
    hashes: Dict[str, str] = {}

    declared_files = {table["file"] for table in manifest.get("tables", [])}
    for table in manifest.get("tables", []):
        filename = table["file"]
        path = root / filename
        if not path.exists():
            tables[_table_key(filename)] = {
                "file": filename,
                "columns": table.get("columns", []),
                "rows": [],
                "missing": True,
            }
            continue
        columns, rows = read_csv(path)
        key = table.get("name") or _table_key(filename)
        tables[key] = {"file": filename, "columns": columns, "rows": rows, "missing": False}
        hashes[filename] = sha256_file(path)

    # Optional tables are useful for age/rating overlays, sessions, lineage and
    # adopted recommendations.  Their absence is normal for the base fixture.
    optional_names = (
        "sessions.csv",
        "segment_lineage.csv",
        "lineage.csv",
        "source_profiles.csv",
        "adopted_recommendations.csv",
        "recommendations.csv",
    )
    for filename in optional_names:
        if filename in declared_files:
            continue
        path = root / filename
        if path.exists():
            columns, rows = read_csv(path)
            tables[_table_key(filename)] = {
                "file": filename,
                "columns": columns,
                "rows": rows,
                "missing": False,
            }
            hashes[filename] = sha256_file(path)

    return {
        "data_dir": str(root),
        "manifest": manifest,
        "tables": tables,
        "hashes": hashes,
    }


def rows(repo: Dict[str, Any], table_name: str) -> List[Dict[str, str]]:
    table = repo.get("tables", {}).get(table_name)
    return list(table["rows"]) if table else []


def index_rows(repo: Dict[str, Any], table_name: str, key: str) -> Dict[str, Dict[str, str]]:
    return {row.get(key, ""): row for row in rows(repo, table_name) if row.get(key)}


def repository_snapshot(repo: Dict[str, Any]) -> Dict[str, Any]:
    """Return JSON-safe rows plus file hashes for committee provenance."""
    files: Dict[str, Any] = {}
    for name, table in repo.get("tables", {}).items():
        filename = table.get("file", f"{name}.csv")
        files[filename] = {
            "table_name": name,
            "sha256": repo.get("hashes", {}).get(filename),
            "columns": table.get("columns", []),
            "rows": table.get("rows", []),
        }
    return {
        "format": "coverage-tool-repository-snapshot",
        "schema_version": 1,
        "data_dir": repo.get("data_dir"),
        "file_hashes": dict(repo.get("hashes", {})),
        "files": files,
    }


def snapshot_to_repository(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a saved snapshot/report back into the loader's repo shape."""
    if "repository_snapshot" in snapshot:
        snapshot = snapshot["repository_snapshot"]
    if snapshot.get("format") == "coverage-tool-repository-snapshot":
        tables = {}
        for filename, payload in snapshot.get("files", {}).items():
            name = payload.get("table_name") or _table_key(filename)
            tables[name] = {
                "file": filename,
                "columns": payload.get("columns", []),
                "rows": payload.get("rows", []),
                "missing": False,
            }
        return {
            "data_dir": snapshot.get("data_dir", "<snapshot>"),
            "manifest": {"tables": []},
            "tables": tables,
            "hashes": snapshot.get("file_hashes", {}),
            "from_snapshot": True,
        }
    raise ValueError("Unsupported snapshot format: no repository_snapshot found")


def load_json(path: PathLike) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: PathLike, payload: Dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False), encoding="utf-8")
    return path
