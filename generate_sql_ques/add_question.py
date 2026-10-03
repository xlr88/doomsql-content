#!/usr/bin/env python3
"""
DoomSQL - Question Builder (content repo version)

Adds a new SQL question to questions/, computes its expectedOutput by actually
running the solution in SQLite, then rebuilds questions/manifest.json.

Usage (run from the repo root):
  python3 generate_sql_ques/add_question.py --interactive
  python3 generate_sql_ques/add_question.py --file drafts/my_question.json
"""

import argparse
import glob
import json
import os
import sqlite3
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
QUESTIONS_DIR = os.path.join(REPO_ROOT, "questions")
BUILD_MANIFEST_SCRIPT = os.path.join(REPO_ROOT, "tools", "build_manifest.py")

VALID_DIFFICULTIES = ("EASY", "MEDIUM", "HARD")
VALID_TYPES = ("INTEGER", "TEXT", "REAL")


def validate_and_compute_expected_output(question_data: dict) -> dict:
    """Build the question's tables in an in-memory SQLite DB, run solutionQuery,
    and return {"columns": [...], "rows": [...]}."""
    tables = question_data.get("tables", [])
    solution_query = question_data.get("solutionQuery", "").strip()

    if not tables:
        raise ValueError("Question must have at least one table definition.")
    if not solution_query:
        raise ValueError("Question must have a non-empty 'solutionQuery'.")

    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    try:
        for table in tables:
            cols_def = []
            for col in table["columns"]:
                if col["type"].upper() not in VALID_TYPES:
                    raise ValueError(
                        f"Column '{col['name']}' has type '{col['type']}'. Use INTEGER, TEXT or REAL."
                    )
                pk = " PRIMARY KEY" if col.get("primaryKey") else ""
                not_null = " NOT NULL" if not col.get("nullable", True) else ""
                cols_def.append(f'"{col["name"]}" {col["type"]}{pk}{not_null}')
            cursor.execute(f'CREATE TABLE "{table["name"]}" ({", ".join(cols_def)});')

            rows = table.get("rows", [])
            for i, row in enumerate(rows):
                if len(row) != len(table["columns"]):
                    raise ValueError(
                        f"Table '{table['name']}' row #{i} has {len(row)} values "
                        f"but the table has {len(table['columns'])} columns."
                    )
            if rows:
                ph = ", ".join(["?"] * len(table["columns"]))
                cursor.executemany(f'INSERT INTO "{table["name"]}" VALUES ({ph});', rows)
        conn.commit()

        cursor.execute(solution_query)
        result_rows = [list(r) for r in cursor.fetchall()]
        result_columns = [d[0] for d in cursor.description] if cursor.description else []
        return {"columns": result_columns, "rows": result_rows}
    finally:
        conn.close()


def existing_questions() -> list:
    out = []
    for path in sorted(glob.glob(os.path.join(QUESTIONS_DIR, "sql_*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                out.append(json.load(f))
        except Exception:
            pass
    return out


def title_exists(title: str) -> bool:
    t = (title or "").strip().lower()
    return any((q.get("title") or "").strip().lower() == t for q in existing_questions())


def get_next_question_id() -> str:
    nums = []
    for path in glob.glob(os.path.join(QUESTIONS_DIR, "sql_*.json")):
        part = os.path.basename(path)[4:-5]
        if part.isdigit():
            nums.append(int(part))
    return f"sql_{(max(nums) + 1) if nums else 1:03d}"


def rebuild_manifest() -> bool:
    print("[*] Rebuilding questions/manifest.json ...")
    res = subprocess.run([sys.executable, BUILD_MANIFEST_SCRIPT], capture_output=True, text=True)
    print((res.stdout + res.stderr).strip())
    return res.returncode == 0


def save_question(question_data: dict, rebuild: bool = True) -> str:
    """Validate, compute expectedOutput, write questions/<id>.json and
    (optionally) rebuild the manifest. Returns the question id."""
    os.makedirs(QUESTIONS_DIR, exist_ok=True)

    difficulty = (question_data.get("difficulty") or "").upper()
    if difficulty not in VALID_DIFFICULTIES:
        raise ValueError(f"difficulty must be EASY, MEDIUM or HARD (got '{difficulty}').")
    question_data["difficulty"] = difficulty

    if title_exists(question_data.get("title")):
        raise ValueError(f"A question titled '{question_data.get('title')}' already exists. "
                         "To change it, edit that file and bump its contentVersion instead.")

    # Always assign a fresh id so drafts copied from the template can't clash.
    q_id = get_next_question_id()
    question_data["id"] = q_id
    question_data.setdefault("contentVersion", 1)
    question_data.setdefault("sqlDialect", "SQLITE")
    question_data.setdefault("orderSensitive", False)
    question_data.setdefault("minAppVersionCode", 1)

    print(f"[*] Running solution for '{q_id}' in SQLite ...")
    output = validate_and_compute_expected_output(question_data)
    question_data["expectedOutput"] = output
    print(f"[✓] Query OK — {len(output['columns'])} columns, {len(output['rows'])} rows.")
    if not output["rows"]:
        print("[!] Warning: the solution returns 0 rows. Is that intended?")

    target = os.path.join(QUESTIONS_DIR, f"{q_id}.json")
    with open(target, "w", encoding="utf-8") as f:
        json.dump(question_data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"[✓] Saved {os.path.relpath(target, REPO_ROOT)}")

    if rebuild and not rebuild_manifest():
        os.remove(target)
        raise SystemExit("[x] Manifest build failed, so the new file was removed. Fix the error above.")
    return q_id


def print_publish_steps(ids):
    print("\n🚀 To publish (no app update needed):")
    print("   git add questions/")
    print(f"   git commit -m \"Add {', '.join(ids)}\"")
    print("   git push origin main")


def interactive_mode():
    print("=== DoomSQL question builder ===")
    title = input("Title: ").strip()
    difficulty = input("Difficulty (EASY / MEDIUM / HARD) [EASY]: ").strip().upper() or "EASY"
    description = input("Description (say which columns to return): ").strip()
    tags = [t.strip().lower() for t in input("Tags (comma separated): ").split(",") if t.strip()]
    order = input("Does row order matter? (y/N): ").strip().lower() == "y"

    tables = []
    while True:
        print(f"\n--- Table {len(tables) + 1} ---")
        name = input("Table name: ").strip()
        print("Columns as name:TYPE[:pk], comma separated. e.g. id:INTEGER:pk, name:TEXT, salary:REAL")
        cols = []
        for c in input("Columns: ").split(","):
            parts = [p.strip() for p in c.split(":")]
            is_pk = len(parts) > 2 and parts[2].lower() in ("pk", "primary", "primarykey")
            cols.append({"name": parts[0], "type": (parts[1] if len(parts) > 1 else "TEXT").upper(),
                         "nullable": not is_pk, "primaryKey": is_pk})
        print('Rows as a JSON array, e.g. [[1, "Alice", 75000], [2, "Bob", 62000]]')
        rows = json.loads(input("Rows: ").strip() or "[]")
        tables.append({"name": name, "columns": cols, "rows": rows})
        if input("Add another table? (y/N): ").strip().lower() != "y":
            break

    solution = input("\nSolution SQL: ").strip()
    explanation = input("Explanation: ").strip()

    q_id = save_question({
        "contentVersion": 1, "title": title, "difficulty": difficulty, "sqlDialect": "SQLITE",
        "tags": tags, "description": description, "orderSensitive": order, "tables": tables,
        "solutionQuery": solution, "explanation": explanation,
    })
    print_publish_steps([q_id])


def main():
    p = argparse.ArgumentParser(description="Add a DoomSQL question to questions/")
    p.add_argument("--file", "-f", help="Draft question JSON (expectedOutput and id can be left out)")
    p.add_argument("--interactive", "-i", action="store_true", help="Step-by-step wizard")
    args = p.parse_args()

    try:
        if args.interactive:
            interactive_mode()
        elif args.file:
            with open(args.file, encoding="utf-8") as f:
                data = json.load(f)
            print_publish_steps([save_question(data)])
        else:
            p.print_help()
    except ValueError as e:
        raise SystemExit(f"[x] {e}")


if __name__ == "__main__":
    main()
