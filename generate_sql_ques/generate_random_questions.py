#!/usr/bin/env python3
"""
DoomSQL - Procedural Random SQL Question Generator
Generates realistic, syntactically valid SQL practice questions with custom schemas,
sample data, solutions, and pre-computed expected outputs.

Usage:
  python3 generate_sql_ques/generate_random_questions.py --count 3 --add
  python3 generate_sql_ques/generate_random_questions.py --count 1 --difficulty MEDIUM --preview
NOTE: questions come from a fixed list of BLUEPRINTS below. Ones whose title is
already in questions/ are skipped, so add new blueprints to get new questions.
"""

import os
import sys
import json
import random
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
sys.path.insert(0, SCRIPT_DIR)

from add_question import save_question, validate_and_compute_expected_output, title_exists, rebuild_manifest, print_publish_steps

# Question blueprints across different domains and difficulty tiers
BLUEPRINTS = [
    # --- EASY BLUEPRINTS ---
    {
        "difficulty": "EASY",
        "tags": ["select", "where", "filter"],
        "title": "High-Value Inventory Products",
        "description": "Find the product name and unit price of all items in the 'Electronics' category with a unit price strictly greater than 150. Return the columns name and unit_price.",
        "orderSensitive": False,
        "tables": [
            {
                "name": "Products",
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "primaryKey": True},
                    {"name": "name", "type": "TEXT", "nullable": False, "primaryKey": False},
                    {"name": "category", "type": "TEXT", "nullable": False, "primaryKey": False},
                    {"name": "unit_price", "type": "REAL", "nullable": False, "primaryKey": False},
                    {"name": "stock", "type": "INTEGER", "nullable": False, "primaryKey": False}
                ],
                "rows": [
                    [1, "Wireless Mouse", "Electronics", 29.99, 120],
                    [2, "Mechanical Keyboard", "Electronics", 119.50, 45],
                    [3, "4K Gaming Monitor", "Electronics", 349.99, 18],
                    [4, "Noise Cancelling Headphones", "Electronics", 199.99, 32],
                    [5, "Ergonomic Office Chair", "Furniture", 249.00, 15],
                    [6, "Standing Desk Converter", "Furniture", 169.00, 8]
                ]
            }
        ],
        "solutionQuery": "SELECT name, unit_price FROM Products WHERE category = 'Electronics' AND unit_price > 150;",
        "explanation": "Filter by category = 'Electronics' and unit_price > 150 using a WHERE clause with the AND operator."
    },
    {
        "difficulty": "EASY",
        "tags": ["aggregate", "group by", "count"],
        "title": "Hospital Department Patient Count",
        "description": "Count how many patients are currently admitted to each department. Return department_name and the total number of patients as patient_count.",
        "orderSensitive": False,
        "tables": [
            {
                "name": "Admissions",
                "columns": [
                    {"name": "admission_id", "type": "INTEGER", "nullable": False, "primaryKey": True},
                    {"name": "patient_name", "type": "TEXT", "nullable": False, "primaryKey": False},
                    {"name": "department_name", "type": "TEXT", "nullable": False, "primaryKey": False},
                    {"name": "room_number", "type": "INTEGER", "nullable": False, "primaryKey": False}
                ],
                "rows": [
                    [101, "Lucas Scott", "Cardiology", 302],
                    [102, "Sarah Connor", "Cardiology", 305],
                    [103, "Ethan Hunt", "Neurology", 412],
                    [104, "Elena Fisher", "Cardiology", 308],
                    [105, "Arthur Dent", "Orthopedics", 204],
                    [106, "Chloe Frazer", "Neurology", 415]
                ]
            }
        ],
        "solutionQuery": "SELECT department_name, COUNT(*) AS patient_count FROM Admissions GROUP BY department_name;",
        "explanation": "Group admissions by department_name and use COUNT(*) to count admissions in each group."
    },
    {
        "difficulty": "EASY",
        "tags": ["order by", "limit", "ranking"],
        "title": "Top 3 Fastest Racing Lap Times",
        "description": "List the driver name and lap_seconds for the top 3 fastest laps recorded. The fastest lap has the lowest lap_seconds. Return driver_name and lap_seconds sorted from fastest to slowest.",
        "orderSensitive": True,
        "tables": [
            {
                "name": "LapTimes",
                "columns": [
                    {"name": "lap_id", "type": "INTEGER", "nullable": False, "primaryKey": True},
                    {"name": "driver_name", "type": "TEXT", "nullable": False, "primaryKey": False},
                    {"name": "track", "type": "TEXT", "nullable": False, "primaryKey": False},
                    {"name": "lap_seconds", "type": "REAL", "nullable": False, "primaryKey": False}
                ],
                "rows": [
                    [1, "Max Verstappen", "Monza", 81.04],
                    [2, "Lewis Hamilton", "Monza", 81.35],
                    [3, "Charles Leclerc", "Monza", 81.18],
                    [4, "Lando Norris", "Monza", 81.72],
                    [5, "Fernando Alonso", "Monza", 82.01],
                    [6, "George Russell", "Monza", 81.44]
                ]
            }
        ],
        "solutionQuery": "SELECT driver_name, lap_seconds FROM LapTimes ORDER BY lap_seconds ASC LIMIT 3;",
        "explanation": "Sort by lap_seconds in ascending order (lowest time first) and restrict the result to 3 rows using LIMIT 3."
    },

    # --- MEDIUM BLUEPRINTS ---
    {
        "difficulty": "MEDIUM",
        "tags": ["group by", "having", "aggregate"],
        "title": "Frequent App Buyers",
        "description": "Find the customer_id of all users who have placed at least 3 orders and whose total spending across all orders exceeds 200. Return customer_id and total_spent.",
        "orderSensitive": False,
        "tables": [
            {
                "name": "CustomerOrders",
                "columns": [
                    {"name": "order_id", "type": "INTEGER", "nullable": False, "primaryKey": True},
                    {"name": "customer_id", "type": "INTEGER", "nullable": False, "primaryKey": False},
                    {"name": "order_amount", "type": "REAL", "nullable": False, "primaryKey": False}
                ],
                "rows": [
                    [1, 101, 75.00],
                    [2, 101, 80.00],
                    [3, 101, 95.00],
                    [4, 102, 150.00],
                    [5, 102, 120.00],
                    [6, 103, 30.00],
                    [7, 103, 40.00],
                    [8, 103, 50.00],
                    [9, 104, 250.00],
                    [10, 104, 60.00],
                    [11, 104, 45.00]
                ]
            }
        ],
        "solutionQuery": "SELECT customer_id, SUM(order_amount) AS total_spent FROM CustomerOrders GROUP BY customer_id HAVING COUNT(*) >= 3 AND SUM(order_amount) > 200;",
        "explanation": "Group by customer_id, then apply filter conditions on aggregate functions using HAVING COUNT(*) >= 3 AND SUM(order_amount) > 200."
    },
    {
        "difficulty": "MEDIUM",
        "tags": ["left join", "null handling", "subquery"],
        "title": "Authors Without Published Books",
        "description": "Find the full name of all authors in the Authors table who have not published any books in the Books catalog. Return a single column named author_name.",
        "orderSensitive": False,
        "tables": [
            {
                "name": "Authors",
                "columns": [
                    {"name": "author_id", "type": "INTEGER", "nullable": False, "primaryKey": True},
                    {"name": "author_name", "type": "TEXT", "nullable": False, "primaryKey": False},
                    {"name": "country", "type": "TEXT", "nullable": False, "primaryKey": False}
                ],
                "rows": [
                    [1, "George Orwell", "United Kingdom"],
                    [2, "Isaac Asimov", "United States"],
                    [3, "Philip K. Dick", "United States"],
                    [4, "Arthur C. Clarke", "United Kingdom"],
                    [5, "Ursula K. Le Guin", "United States"]
                ]
            },
            {
                "name": "Books",
                "columns": [
                    {"name": "book_id", "type": "INTEGER", "nullable": False, "primaryKey": True},
                    {"name": "title", "type": "TEXT", "nullable": False, "primaryKey": False},
                    {"name": "author_id", "type": "INTEGER", "nullable": False, "primaryKey": False}
                ],
                "rows": [
                    [101, "1984", 1],
                    [102, "Animal Farm", 1],
                    [103, "Foundation", 2],
                    [104, "I, Robot", 2],
                    [105, "The Left Hand of Darkness", 5]
                ]
            }
        ],
        "solutionQuery": "SELECT a.author_name FROM Authors a LEFT JOIN Books b ON a.author_id = b.author_id WHERE b.book_id IS NULL;",
        "explanation": "Perform a LEFT JOIN between Authors and Books on author_id. Authors with no matches will have NULL for b.book_id."
    },
    {
        "difficulty": "MEDIUM",
        "tags": ["case when", "conditional logic", "aggregate"],
        "title": "Movie Rating Classification",
        "description": "Categorize movies based on their average score. A movie with score >= 8.5 is 'Masterpiece', between 7.0 and 8.4 is 'Recommended', and below 7.0 is 'Average'. Return title, score, and classification, ordered by score descending, then title ascending.",
        "orderSensitive": True,
        "tables": [
            {
                "name": "Movies",
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "primaryKey": True},
                    {"name": "title", "type": "TEXT", "nullable": False, "primaryKey": False},
                    {"name": "score", "type": "REAL", "nullable": False, "primaryKey": False}
                ],
                "rows": [
                    [1, "Interstellar", 8.7],
                    [2, "The Matrix", 8.7],
                    [3, "Arrival", 7.9],
                    [4, "Tenet", 7.3],
                    [5, "Jupiter Ascending", 5.3],
                    [6, "Blade Runner 2049", 8.0]
                ]
            }
        ],
        "solutionQuery": "SELECT title, score, CASE WHEN score >= 8.5 THEN 'Masterpiece' WHEN score >= 7.0 THEN 'Recommended' ELSE 'Average' END AS classification FROM Movies ORDER BY score DESC, title ASC;",
        "explanation": "Use a CASE WHEN expression to evaluate multiple score boundaries and assign the matching text label."
    },

    # --- HARD BLUEPRINTS ---
    {
        "difficulty": "HARD",
        "tags": ["window function", "dense_rank", "partition"],
        "title": "Top Earner in Each Branch",
        "description": "For each bank branch, determine the employee who earns the highest salary. If there is a tie for the top salary, include all tied employees. Return branch, employee_name, and salary, ordered by branch ascending, salary descending, then employee_name ascending.",
        "orderSensitive": True,
        "tables": [
            {
                "name": "BankEmployees",
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "primaryKey": True},
                    {"name": "employee_name", "type": "TEXT", "nullable": False, "primaryKey": False},
                    {"name": "branch", "type": "TEXT", "nullable": False, "primaryKey": False},
                    {"name": "salary", "type": "REAL", "nullable": False, "primaryKey": False}
                ],
                "rows": [
                    [1, "Sarah", "Downtown", 92000.0],
                    [2, "Daniel", "Downtown", 95000.0],
                    [3, "Marcus", "Downtown", 88000.0],
                    [4, "Jessica", "Uptown", 89000.0],
                    [5, "David", "Uptown", 89000.0],
                    [6, "Emily", "Uptown", 76000.0],
                    [7, "Robert", "Suburbs", 82000.0],
                    [8, "Chloe", "Suburbs", 84000.0]
                ]
            }
        ],
        "solutionQuery": "WITH Ranked AS (SELECT branch, employee_name, salary, DENSE_RANK() OVER (PARTITION BY branch ORDER BY salary DESC) as rank_num FROM BankEmployees) SELECT branch, employee_name, salary FROM Ranked WHERE rank_num = 1 ORDER BY branch ASC, salary DESC, employee_name ASC;",
        "explanation": "Use a Common Table Expression (CTE) with DENSE_RANK() partitioned by branch and ordered by salary descending, then filter where rank_num = 1."
    },
    {
        "difficulty": "HARD",
        "tags": ["cte", "window function", "running total"],
        "title": "Cumulative Daily Revenue",
        "description": "Calculate the cumulative total revenue day-by-day. Return sale_date, daily_revenue, and running_total ordered chronologically by sale_date ascending.",
        "orderSensitive": True,
        "tables": [
            {
                "name": "DailySales",
                "columns": [
                    {"name": "sale_id", "type": "INTEGER", "nullable": False, "primaryKey": True},
                    {"name": "sale_date", "type": "TEXT", "nullable": False, "primaryKey": False},
                    {"name": "daily_revenue", "type": "REAL", "nullable": False, "primaryKey": False}
                ],
                "rows": [
                    [1, "2026-03-01", 1250.00],
                    [2, "2026-03-02", 980.50],
                    [3, "2026-03-03", 1420.00],
                    [4, "2026-03-04", 850.25],
                    [5, "2026-03-05", 2100.00]
                ]
            }
        ],
        "solutionQuery": "SELECT sale_date, daily_revenue, SUM(daily_revenue) OVER (ORDER BY sale_date ASC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_total FROM DailySales ORDER BY sale_date ASC;",
        "explanation": "Use SUM(daily_revenue) OVER (ORDER BY sale_date ASC) window function to calculate a cumulative running total across rows."
    }
]


def generate_question(blueprint: dict) -> dict:
    """
    Takes a blueprint, validates it in SQLite, computes the exact expectedOutput,
    and returns the fully resolved question dictionary.
    """
    q_data = {
        "contentVersion": 1,
        "title": blueprint["title"],
        "difficulty": blueprint["difficulty"],
        "sqlDialect": "SQLITE",
        "tags": blueprint["tags"],
        "description": blueprint["description"],
        "orderSensitive": blueprint.get("orderSensitive", False),
        "tables": blueprint["tables"],
        "solutionQuery": blueprint["solutionQuery"],
        "explanation": blueprint["explanation"]
    }
    expected = validate_and_compute_expected_output(q_data)
    q_data["expectedOutput"] = expected
    return q_data


def main():
    parser = argparse.ArgumentParser(description="Procedural SQL Question Generator for DoomSQL")
    parser.add_argument("--count", "-c", type=int, default=1, help="Number of questions to generate (default: 1)")
    parser.add_argument("--difficulty", "-d", choices=["EASY", "MEDIUM", "HARD", "ANY"], default="ANY", help="Filter by difficulty")
    parser.add_argument("--add", action="store_true", help="Save to questions/ and rebuild manifest.json")
    parser.add_argument("--preview", action="store_true", help="Print question JSON to stdout without saving")

    args = parser.parse_args()

    # Filter candidate blueprints
    candidates = BLUEPRINTS
    if args.difficulty != "ANY":
        candidates = [b for b in candidates if b["difficulty"] == args.difficulty]

    if args.add:
        candidates = [b for b in candidates if not title_exists(b["title"])]

    if not candidates:
        print(f"No unused blueprints left for difficulty {args.difficulty}. "
              "Add new entries to BLUEPRINTS in this file.", file=sys.stderr)
        sys.exit(1)

    # Randomly select blueprints
    count = min(args.count, len(candidates))
    selected = random.sample(candidates, count)

    print(f"=== Generating {len(selected)} Random SQL Questions ===")
    added = []

    for i, bp in enumerate(selected, 1):
        q = generate_question(bp)
        print(f"\n[{i}/{len(selected)}] Generated: '{q['title']}' ({q['difficulty']})")
        print(f"    Tags: {', '.join(q['tags'])}")
        print(f"    Query: {q['solutionQuery']}")
        print(f"    Expected rows: {len(q['expectedOutput']['rows'])}, columns: {q['expectedOutput']['columns']}")

        if args.preview:
            print("\n--- JSON Preview ---")
            print(json.dumps(q, indent=2))

        if args.add:
            added.append(save_question(q, rebuild=False))

    if added:
        if not rebuild_manifest():
            sys.exit("[x] Manifest build failed. Fix the error above before committing.")
        print_publish_steps(added)
    print("\nDone! 🎉")


if __name__ == "__main__":
    main()
