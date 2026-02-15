from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pandas as pd

EXPORT_COLUMNS = [
    "id",
    "de",
    "en",
    "de_desc",
    "en_desc",
    "chapter_ids",
    "synonyms_json",
    "annotations_json",
]


def export_terms(rows: list[dict[str, Any]], target: Path) -> None:
    suffix = target.suffix.lower()
    normalized = [
        {
            "id": row.get("id"),
            "de": row.get("de", ""),
            "en": row.get("en", ""),
            "de_desc": row.get("de_desc", ""),
            "en_desc": row.get("en_desc", ""),
            "chapter_ids": json.dumps(row.get("chapter_ids", []), ensure_ascii=False),
            "synonyms_json": json.dumps(row.get("synonyms", []), ensure_ascii=False),
            "annotations_json": json.dumps(row.get("annotations", []), ensure_ascii=False),
        }
        for row in rows
    ]

    if suffix == ".json":
        target.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    if suffix == ".csv":
        with target.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=EXPORT_COLUMNS)
            writer.writeheader()
            writer.writerows(normalized)
        return

    if suffix in {".xlsx", ".xls"}:
        pd.DataFrame(normalized, columns=EXPORT_COLUMNS).to_excel(target, index=False)
        return

    raise ValueError(f"unsupported export format: {suffix}")


def import_terms(source: Path) -> list[dict[str, Any]]:
    suffix = source.suffix.lower()
    if suffix == ".json":
        rows = json.loads(source.read_text(encoding="utf-8"))
    elif suffix == ".csv":
        with source.open("r", encoding="utf-8", newline="") as fp:
            rows = list(csv.DictReader(fp))
    elif suffix in {".xlsx", ".xls"}:
        rows = pd.read_excel(source).to_dict("records")
    else:
        raise ValueError(f"unsupported import format: {suffix}")

    output: list[dict[str, Any]] = []
    for row in rows:
        chapter_ids = row.get("chapter_ids", "[]")
        synonyms = row.get("synonyms_json", "[]")
        annotations = row.get("annotations_json", "[]")
        output.append(
            {
                "de": str(row.get("de", "")).strip(),
                "en": str(row.get("en", "")).strip(),
                "de_desc": str(row.get("de_desc", "")).strip(),
                "en_desc": str(row.get("en_desc", "")).strip(),
                "chapter_ids": json.loads(chapter_ids) if isinstance(chapter_ids, str) else chapter_ids,
                "synonyms": json.loads(synonyms) if isinstance(synonyms, str) else (synonyms or []),
                "annotations": json.loads(annotations)
                if isinstance(annotations, str)
                else (annotations or []),
            }
        )
    return output
