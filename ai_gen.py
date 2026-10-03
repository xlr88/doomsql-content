#!/usr/bin/env python3
"""
DoomSQL — AI question generator
================================

Generates new SQL questions with an AI model, runs them through every DoomSQL
check, adds them to questions/, rebuilds manifest.json and (optionally)
commits + pushes so users get them without an app update.

Usage (run from the doomsql-content folder):

  python3 ai_gen.py man  --e 5 --m 6 --h 2     # generate + check + save, YOU commit/push
  python3 ai_gen.py auto --e 5 --m 6 --h 2     # same, then git commit + push automatically
  python3 ai_gen.py dry  --e 1 --m 1           # generate + check, save NOTHING (try it out)

Useful options:
  --topic "window functions"     focus every question on a topic
  --provider gemini|openai|anthropic   override AI_PROVIDER from .env
  --no-crosscheck                skip the "second opinion" check (faster, cheaper, riskier)

API keys live in a .env file next to this script (never committed — see .env.example).
"""

import argparse
import datetime as dt
import difflib
import json
import os
import random
import re
import sqlite3
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO, "generate_sql_ques"))
from add_question import (  # noqa: E402
    existing_questions, rebuild_manifest, save_question,
    validate_and_compute_expected_output, VALID_TYPES,
)

MAX_PER_RUN = 40
LOG_DIR = os.path.join(REPO, "ai_runs")

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5-5",
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4.1-mini",
}

TOPICS = {
    "EASY": ["SELECT + WHERE filters", "DISTINCT", "ORDER BY + LIMIT", "COUNT/SUM/AVG/MIN/MAX",
             "basic GROUP BY", "simple INNER JOIN", "NULL handling (IS NULL, COALESCE)",
             "basic CASE WHEN", "LIKE / IN / BETWEEN", "string functions (UPPER, LENGTH, SUBSTR)"],
    "MEDIUM": ["multiple JOINs", "GROUP BY + HAVING", "subqueries in WHERE", "correlated subqueries",
               "CTEs (WITH)", "ROW_NUMBER / RANK / DENSE_RANK", "LAG / LEAD", "duplicate detection",
               "date functions (strftime, date)", "conditional aggregation (SUM(CASE ...))",
               "LEFT JOIN anti-join", "self join", "UNION / EXCEPT"],
    "HARD": ["multiple window functions", "gaps and islands", "running totals and moving averages",
             "top-N per group with ties", "recursive CTEs", "month-over-month growth",
             "retention / cohort analysis", "consecutive streaks", "median or percentiles",
             "complex multi-step CTE pipelines"],
}

SYSTEM_PROMPT = "You write SQL interview practice questions for a mobile app. You always reply with valid JSON only."

GEN_PROMPT = """Create {n} NEW {difficulty} SQL interview practice questions.

Topics to draw from (vary them, one main topic per question): {topics}

STRICT RULES — questions breaking any rule are thrown away:
1. Dialect is SQLite 3.39+. Allowed: CTEs, window functions, strftime/date. NOT allowed: TOP, ILIKE,
   DATE_TRUNC, RIGHT/FULL JOIN, ::casts, stored procedures, RANDOM(), date('now'), CURRENT_DATE.
2. solutionQuery is ONE read-only statement starting with SELECT or WITH. No semicolons inside.
3. The description must name EVERY output column exactly as the solution aliases it
   (e.g. "Return customer_name and total_spent").
4. Set "orderSensitive": true ONLY if the solution has a final ORDER BY, and then the description
   must state the full ordering including tie-breakers (e.g. "ordered by total_spent descending,
   then customer_name ascending"). Otherwise false.
5. Results must be deterministic: no ties that could change which rows appear (e.g. with LIMIT)
   unless the description says exactly how ties are handled.
6. Column types: only INTEGER, TEXT, REAL. Dates are TEXT 'YYYY-MM-DD'.
7. 1–3 tables, 5–15 realistic rows each. Include edge cases that make naive answers wrong
   (NULLs, duplicates, ties, missing matches) where it suits the topic.
8. The solution must return at least 1 row.
9. Use realistic business domains (e-commerce, banking, HR, streaming, logistics, healthcare,
   ride-sharing, SaaS, education, sports). Vary domains.
10. Titles must be short (max 6 words) and NOT similar to any of these existing titles:
{existing}
{topic_line}
Reply with ONLY this JSON shape:
{{"questions": [
  {{
    "title": "...",
    "difficulty": "{difficulty}",
    "tags": ["join", "group by"],
    "description": "...",
    "orderSensitive": false,
    "tables": [
      {{"name": "Orders",
        "columns": [{{"name": "id", "type": "INTEGER", "nullable": false, "primaryKey": true}},
                    {{"name": "amount", "type": "REAL", "nullable": true, "primaryKey": false}}],
        "rows": [[1, 20.5], [2, null]]}}
    ],
    "solutionQuery": "SELECT ...",
    "explanation": "2-4 sentences on the approach and the key clause."
  }}
]}}"""

SOLVE_PROMPT = """Solve this SQL problem in SQLite. Return ONLY JSON: {{"query": "SELECT ..."}}

Problem: {description}

Tables (with sample rows):
{tables}
"""

BANNED_SQL = re.compile(
    r"\b(ATTACH|DETACH|PRAGMA|VACUUM|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|"
    r"RANDOM|CURRENT_DATE|CURRENT_TIME|CURRENT_TIMESTAMP)\b|date\(\s*'now'", re.I)


# ----------------------------------------------------------------------------- env + AI
def load_env():
    path = os.path.join(REPO, ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def ssl_context():
    try:
        import certifi  # fixes CERTIFICATE_VERIFY_FAILED on python.org macOS installs
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def http_json(url, headers, body, timeout=180):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}") from None


class AI:
    def __init__(self, provider=None):
        self.provider = (provider or os.environ.get("AI_PROVIDER") or "gemini").lower()
        if self.provider == "claude":
            self.provider = "anthropic"
        key_names = {"anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY"}
        if self.provider == "mock":  # used by tests only
            self.key, self.model = "", "mock"
            return
        if self.provider not in key_names:
            sys.exit(f"[x] Unknown AI_PROVIDER '{self.provider}'. Use gemini, openai or anthropic.")
        self.key = os.environ.get(key_names[self.provider], "")
        if not self.key:
            sys.exit(f"[x] {key_names[self.provider]} is missing. Put it in .env (see .env.example).")
        self.model = os.environ.get("AI_MODEL") or DEFAULT_MODELS[self.provider]
        self.calls = 0

    def ask(self, prompt, temperature=0.9):
        last = None
        for attempt in range(3):
            try:
                self.calls = getattr(self, "calls", 0) + 1
                return parse_json(self._call(prompt, temperature))
            except Exception as e:  # network blip, rate limit, bad JSON → retry
                last = e
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"AI request failed after 3 tries: {last}")

    def _call(self, prompt, temperature):
        if self.provider == "mock":
            return MOCK_RESPONDER(prompt)
        if self.provider == "anthropic":
            r = http_json("https://api.anthropic.com/v1/messages",
                          {"x-api-key": self.key, "anthropic-version": "2023-06-01"},
                          {"model": self.model, "max_tokens": 16000, "temperature": temperature,
                           "system": SYSTEM_PROMPT, "messages": [{"role": "user", "content": prompt}]})
            return "".join(b.get("text", "") for b in r.get("content", []))
        if self.provider == "gemini":
            r = http_json(f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                          {"x-goog-api-key": self.key},
                          {"systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                           "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                           "generationConfig": {"responseMimeType": "application/json",
                                                "temperature": temperature}})
            return "".join(p.get("text", "") for p in r["candidates"][0]["content"]["parts"])
        # openai
        r = http_json("https://api.openai.com/v1/chat/completions",
                      {"Authorization": f"Bearer {self.key}"},
                      {"model": self.model, "response_format": {"type": "json_object"},
                       "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                    {"role": "user", "content": prompt}]})
        return r["choices"][0]["message"]["content"]


MOCK_RESPONDER = None  # tests replace this with a function(prompt) -> str


def parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON object in AI reply")
    return json.loads(text[start:end + 1])


# ----------------------------------------------------------------------------- checks
def norm_title(t):
    return re.sub(r"[^a-z0-9 ]", "", (t or "").lower()).strip()


def too_similar(title, titles):
    n = norm_title(title)
    for other in titles:
        o = norm_title(other)
        if n == o or difflib.SequenceMatcher(None, n, o).ratio() >= 0.85:
            return other
    return None


def run_query(q, sql, shuffle_seed=None):
    """Run sql against q's tables. With shuffle_seed the rows are inserted in a
    shuffled order (seed 0 = reversed), which exposes answers that depend on
    insertion order, i.e. unstated tie-breaks."""
    conn = sqlite3.connect(":memory:")
    try:
        for t in q["tables"]:
            # In shuffled runs we drop PRIMARY KEY: an INTEGER PRIMARY KEY is the rowid,
            # which would keep scan order fixed and hide insertion-order dependence.
            cols = ", ".join(
                f'"{c["name"]}" {c["type"]}' + (" PRIMARY KEY" if c.get("primaryKey") and shuffle_seed is None else "")
                + ("" if c.get("nullable", True) else " NOT NULL") for c in t["columns"])
            conn.execute(f'CREATE TABLE "{t["name"]}" ({cols})')
            rows = list(t["rows"])
            if shuffle_seed == 0:
                rows.reverse()
            elif shuffle_seed is not None:
                random.Random(shuffle_seed).shuffle(rows)
            if rows:
                conn.executemany(f'INSERT INTO "{t["name"]}" VALUES ({", ".join("?" * len(t["columns"]))})', rows)
        cur = conn.execute(sql)
        return [d[0] for d in cur.description or []], [list(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _cell(v):
    if isinstance(v, bool) or v is None:
        return (0, "") if v is None else (1, float(v))
    if isinstance(v, (int, float)):
        return (1, round(float(v), 6))
    try:
        return (1, round(float(v), 6))
    except (TypeError, ValueError):
        return (2, str(v).strip())


def same_result(a_cols, a_rows, b_cols, b_rows, ordered):
    if [c.lower() for c in a_cols] != [c.lower() for c in b_cols]:
        return False
    a = [tuple(_cell(v) for v in r) for r in a_rows]
    b = [tuple(_cell(v) for v in r) for r in b_rows]
    return a == b if ordered else sorted(a) == sorted(b)


def check_question(q, existing_titles, ai, crosscheck):
    """Return None if q is good, else a short reason it was rejected."""
    for k in ("title", "difficulty", "description", "tables", "solutionQuery", "explanation"):
        if not q.get(k):
            return f"missing '{k}'"
    if q["difficulty"] not in TOPICS:
        return f"bad difficulty {q['difficulty']}"
    sim = too_similar(q["title"], existing_titles)
    if sim:
        return f"title too similar to existing '{sim}'"
    if not isinstance(q["tables"], list) or not 1 <= len(q["tables"]) <= 4:
        return "needs 1–4 tables"
    for t in q["tables"]:
        if not t.get("rows") or len(t["rows"]) > 40:
            return f"table {t.get('name')} needs 1–40 rows"
        for c in t["columns"]:
            if str(c.get("type", "")).upper() not in VALID_TYPES:
                return f"column {c.get('name')} has type {c.get('type')}"
            c["type"] = c["type"].upper()
            c.setdefault("nullable", not c.get("primaryKey", False))
            c.setdefault("primaryKey", False)

    sql = q["solutionQuery"].strip().rstrip(";").strip()
    q["solutionQuery"] = sql
    if ";" in sql:
        return "solution has more than one statement"
    if not re.match(r"^\s*(SELECT|WITH)\b", sql, re.I):
        return "solution must start with SELECT or WITH"
    if BANNED_SQL.search(sql):
        return "solution uses a banned keyword"

    try:
        cols, rows = run_query(q, sql)
    except Exception as e:
        return f"solution fails in SQLite: {e}"
    if not rows:
        return "solution returns 0 rows"
    if len(set(c.lower() for c in cols)) != len(cols):
        return "duplicate output column names"
    desc = q["description"].lower()
    missing = [c for c in cols if c.lower() not in desc]
    if missing:
        return f"description doesn't name output column(s) {missing}"

    ordered = bool(q.get("orderSensitive"))
    has_order = re.search(r"\border\s+by\b[^()]*$", sql, re.I | re.S) is not None
    if ordered and not has_order:
        return "orderSensitive but no final ORDER BY"
    if ordered and not re.search(r"order|sort|descending|ascending", desc):
        return "orderSensitive but description doesn't state the order"

    for seed in range(6):
        try:
            r_cols, r_rows = run_query(q, sql, shuffle_seed=seed)
        except Exception as e:
            return f"solution unstable: {e}"
        if not same_result(cols, rows, r_cols, r_rows, ordered):
            return "result depends on row order (ties with no stated tie-break)"

    if crosscheck:
        tables_txt = "\n".join(
            f'{t["name"]}({", ".join(c["name"] + " " + c["type"] for c in t["columns"])})\n'
            + "\n".join(json.dumps(r) for r in t["rows"]) for t in q["tables"])
        try:
            ans = ai.ask(SOLVE_PROMPT.format(description=q["description"], tables=tables_txt), temperature=0.2)
            a_sql = str(ans.get("query", "")).strip().rstrip(";")
            if BANNED_SQL.search(a_sql) or not re.match(r"^\s*(SELECT|WITH)\b", a_sql, re.I):
                return "cross-check answer was not a safe SELECT"
            a_cols, a_rows = run_query(q, a_sql)
        except Exception as e:
            return f"cross-check failed: {e}"
        if not same_result(cols, rows, a_cols, a_rows, ordered):
            return "cross-check: an independent solver got a different answer (question is ambiguous)"
    return None


# ----------------------------------------------------------------------------- git
def git(*args, check=True):
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{r.stdout}{r.stderr}")
    return r.stdout.strip()


def git_preflight():
    if git("status", "--porcelain", "questions/"):
        sys.exit("[x] questions/ has uncommitted changes. Commit or discard them first, "
                 "so auto mode only pushes what it generated.")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main":
        sys.exit(f"[x] You're on branch '{branch}'. The app reads from 'main' — switch with: git checkout main")
    print("[*] git pull (so we build on the latest questions) ...")
    git("pull", "--ff-only")


# ----------------------------------------------------------------------------- main flow
def generate(ai, counts, topic, crosscheck, log):
    existing = existing_questions()
    titles = [q.get("title", "") for q in existing]
    accepted = []
    for diff, want in counts.items():
        if want <= 0:
            continue
        got, rounds = [], 0
        while len(got) < want and rounds < 4:
            rounds += 1
            need = want - len(got)
            ask_n = min(need + max(1, need // 3), 15)  # ask a few extra; some get rejected
            topics = TOPICS[diff][:]
            random.shuffle(topics)
            prompt = GEN_PROMPT.format(
                n=ask_n, difficulty=diff, topics="; ".join(topics),
                existing="\n".join(f"- {t}" for t in titles) or "- (none)",
                topic_line=f"\nEvery question must focus on: {topic}\n" if topic else "")
            print(f"[*] {diff}: asking AI for {ask_n} (round {rounds}) ...")
            try:
                batch = ai.ask(prompt).get("questions", [])
            except Exception as e:
                print(f"    [!] {e}")
                log.append(f"- {diff} round {rounds}: AI error {e}")
                continue
            for q in batch:
                if len(got) >= want:
                    break
                q["difficulty"] = str(q.get("difficulty", diff)).upper()
                reason = check_question(q, titles, ai, crosscheck)
                if reason:
                    print(f"    [✗] {q.get('title', '?')}: {reason}")
                    log.append(f"- ✗ [{diff}] {q.get('title', '?')} — {reason}")
                    continue
                print(f"    [✓] {q['title']}")
                titles.append(q["title"])
                got.append(q)
        if len(got) < want:
            print(f"    [!] only {len(got)}/{want} {diff} questions passed all checks")
        accepted += got
    return accepted


def main():
    load_env()
    p = argparse.ArgumentParser(description="Generate DoomSQL questions with AI.",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("mode", choices=["auto", "man", "dry"],
                   help="auto = commit+push, man = save only (you push), dry = save nothing")
    p.add_argument("-e", "--e", "--easy", dest="e", type=int, default=0)
    p.add_argument("-m", "--m", "--medium", dest="m", type=int, default=0)
    p.add_argument("-H", "--h", "--hard", dest="h", type=int, default=0)
    p.add_argument("--topic", help='focus topic, e.g. "window functions"')
    p.add_argument("--provider", help="gemini | openai | anthropic (overrides .env)")
    p.add_argument("--no-crosscheck", action="store_true", help="skip the independent-solver check")
    a = p.parse_args()

    counts = {"EASY": a.e, "MEDIUM": a.m, "HARD": a.h}
    total = sum(counts.values())
    if total <= 0:
        p.error("ask for at least one question, e.g. --e 2 --m 2 --h 1")
    if total > MAX_PER_RUN:
        p.error(f"max {MAX_PER_RUN} questions per run")

    ai = AI(a.provider)
    if a.mode == "auto":
        git_preflight()

    print(f"=== DoomSQL AI generator — {ai.provider} / {ai.model} — "
          f"{a.e} easy, {a.m} medium, {a.h} hard ({a.mode} mode) ===")
    log = []
    accepted = generate(ai, counts, a.topic, not a.no_crosscheck, log)

    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"{stamp}_{a.mode}.md")

    if not accepted:
        open(log_path, "w").write("# No questions accepted\n\n" + "\n".join(log) + "\n")
        sys.exit(f"[x] No questions passed the checks. Details: {os.path.relpath(log_path, REPO)}")

    if a.mode == "dry":
        print("\n--- DRY RUN: nothing saved. Accepted questions: ---")
        for q in accepted:
            print(json.dumps(q, indent=2))
        open(log_path, "w").write("# Dry run\n\n" + "\n".join(log) + "\n")
        return

    ids = []
    try:
        for q in accepted:
            q.update({"contentVersion": 1, "sqlDialect": "SQLITE", "minAppVersionCode": 1})
            q["tags"] = [str(t).lower() for t in q.get("tags", [])][:6]
            q.pop("id", None)
            q.pop("expectedOutput", None)
            ids.append(save_question(q, rebuild=False))
    except Exception as e:
        print(f"[x] Saving failed: {e}")
        for i in ids:
            os.remove(os.path.join(REPO, "questions", f"{i}.json"))
        sys.exit(1)

    ok = rebuild_manifest()
    v = subprocess.run([sys.executable, os.path.join(REPO, "generate_sql_ques", "validate_questions.py")],
                       capture_output=True, text=True)
    if not ok or v.returncode != 0:
        print(v.stdout[-2000:])
        for i in ids:
            os.remove(os.path.join(REPO, "questions", f"{i}.json"))
        rebuild_manifest()
        sys.exit("[x] Final validation failed — new files removed, nothing committed.")

    summary = [f"# AI run {stamp} ({a.mode})", "",
               f"Provider: {ai.provider} / {ai.model}", f"Added: {', '.join(ids)}", ""]
    for i, q in zip(ids, accepted):
        summary += [f"## {i} — {q['title']} ({q['difficulty']})", "", q["description"], "",
                    "```sql", q["solutionQuery"], "```", ""]
    summary += ["## Rejected", ""] + (log or ["(none)"])
    open(log_path, "w").write("\n".join(summary) + "\n")

    msg = (f"AI: add {len(ids)} questions ({sum(q['difficulty']=='EASY' for q in accepted)}E/"
           f"{sum(q['difficulty']=='MEDIUM' for q in accepted)}M/"
           f"{sum(q['difficulty']=='HARD' for q in accepted)}H) {ids[0]}" + (f"–{ids[-1]}" if len(ids) > 1 else ""))
    print(f"\n[✓] Added {len(ids)} questions: {', '.join(ids)}")
    print(f"[✓] Review log: {os.path.relpath(log_path, REPO)}")

    if a.mode == "auto":
        git("add", "questions/")
        try:
            git("commit", "-m", msg)
        except RuntimeError as e:
            sys.exit(f"[x] Questions saved but git commit failed — commit/push yourself.\n{e}")
        print("[*] git push ...")
        try:
            git("push")
        except RuntimeError as e:
            sys.exit(f"[x] Commit made but push failed — run 'git push' yourself.\n{e}")
        print("[✓] Pushed. Users get these within ~24h (or tap 'Check for new questions').")
    else:
        print("\nTo publish:")
        print("   git add questions/")
        print(f'   git commit -m "{msg}"')
        print("   git push")


if __name__ == "__main__":
    main()
