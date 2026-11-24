import csv
import json
from pathlib import Path
from typing import Dict, Optional, Union

ROOT = Path(__file__).resolve().parent


def inspect_inputs(data_dir: Optional[Union[str, Path]] = None) -> Dict[str, int]:
    """Read every manifest-declared table and verify its contract.

    The optional ``data_dir`` argument makes the audit reusable against
    temporary revision fixtures.  With no argument it preserves the original
    behaviour of auditing ``./data``.
    """
    root = Path(data_dir) if data_dir is not None else ROOT / "data"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    counts = {}
    for table in manifest["tables"]:
        path = root / table["file"]
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != table["columns"]:
                raise ValueError(f"{table['file']}: unexpected columns")
            rows = list(reader)

        key = table.get("key")
        if key:
            values = [row[key] for row in rows]
            if len(values) != len(set(values)):
                raise ValueError(f"{table['file']}: duplicate {key}")

        for composite_key in table.get("unique_keys", []):
            values = [tuple(row[part] for part in composite_key) for row in rows]
            if len(values) != len(set(values)):
                joined = ",".join(composite_key)
                raise ValueError(f"{table['file']}: duplicate ({joined})")

        counts[table["file"]] = len(rows)
    return counts


if __name__ == "__main__":
    for filename, count in inspect_inputs().items():
        print(f"{filename}: {count} rows")
