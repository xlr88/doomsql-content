#!/usr/bin/env python3
"""Build manifest.json for DoomSQL and verify every question is correct."""

import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

QUESTIONS_DIR = Path(__file__).resolve().parent.parent / "questions"
MANIFEST = QUESTIONS_DIR / "manifest.json"


def build_db(question):
    """Create an in-memory DB with this question's tables and sample rows."""
    conn = sqlite3.connect(":memory:")
    for table in question["tables"]:
        cols = ", ".join(
            f'"{c["name"]}" {c["type"]}'
            + (" PRIMARY KEY" if c.get("primaryKey") else "")
            + ("" if c.get("nullable", True) else " NOT NULL")
            for c in table["columns"]
        )
        conn.execute(f'CREATE TABLE "{table["name"]}" ({cols})')
        placeholders = ", ".join("?" * len(table["columns"]))
        conn.executemany(
            f'INSERT INTO "{table["name"]}" VALUES ({placeholders})', table["rows"]
        )
    return conn


def normalize(rows, order_sensitive):
    """Match the app's comparison rules closely enough to catch real errors."""
    out = [
        tuple(
            float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
            for v in row
        )
        for row in rows
    ]
    if order_sensitive:
        return out
    return sorted(out, key=lambda r: [
        (0,) if v is None else (1, v) if isinstance(v, float) else (2, str(v))
        for v in r
    ])


def verify(question):
    """Run solutionQuery and confirm it matches expectedOutput."""
    conn = build_db(question)
    actual = conn.execute(question["solutionQuery"]).fetchall()
    conn.close()

    expected = question["expectedOutput"]["rows"]
    declared_cols = len(question["expectedOutput"]["columns"])
    order_sensitive = question.get("orderSensitive", False)

    if actual and len(actual[0]) != declared_cols:
        raise ValueError(
            f"column count mismatch: solution returned {len(actual[0])}, "
            f"expectedOutput declares {declared_cols}"
        )
    if normalize(actual, order_sensitive) != normalize(expected, order_sensitive):
        raise ValueError(
            "solution does not match expectedOutput\n"
            f"  expected: {expected}\n"
            f"  actual:   {actual}"
        )


def main():
    if not QUESTIONS_DIR.exists():
        QUESTIONS_DIR.mkdir(parents=True, exist_ok=True)

    previous_version = 0
    previous_added = {}
    if MANIFEST.exists():
        old = json.loads(MANIFEST.read_text())
        previous_version = old.get("manifestVersion", 0)
        previous_added = {q["id"]: q.get("addedAt") for q in old.get("questions", [])}

    entries, failures, seen_ids = [], [], set()

    question_files = sorted(QUESTIONS_DIR.glob("sql_*.json"))
    if not question_files:
        print(f"Warning: No sql_*.json files found in {QUESTIONS_DIR}")

    for path in question_files:
        raw = path.read_bytes()
        try:
            question = json.loads(raw)
        except json.JSONDecodeError as exc:
            failures.append(f"{path.name}: invalid JSON — {exc}")
            continue

        if question.get("id") in seen_ids:
            failures.append(f"{path.name}: duplicate id {question.get('id')}")
            continue
        seen_ids.add(question.get("id"))

        try:
            verify(question)
        except Exception as exc:
            failures.append(f"{path.name}: {exc}")
            continue

        entries.append({
            "id": question["id"],
            "file": path.name,
            "contentVersion": question.get("contentVersion", 1),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "minAppVersionCode": question.get("minAppVersionCode", 1),
            "difficulty": question["difficulty"],
            "title": question["title"],
            "addedAt": previous_added.get(question["id"]) or date.today().isoformat(),
        })

    if failures:
        print("MANIFEST NOT WRITTEN — fix these first:\n")
        for f in failures:
            print(f"  x {f}")
        raise SystemExit(1)

    MANIFEST.write_text(json.dumps({
        "manifestVersion": previous_version + 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "questions": entries,
    }, indent=2) + "\n")

    print(f"OK  {len(entries)} questions verified")
    print(f"OK  manifest.json written at version {previous_version + 1}")


if __name__ == "__main__":
    main()
