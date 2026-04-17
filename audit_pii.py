#!/usr/bin/env python3
"""PII audit over the tenders table — counts records that would be anonymized
by the export, broken down by detection rule. Produces a Markdown report.

Usage:
    python audit_pii.py --output PII_AUDIT.md
    python audit_pii.py --year 2024 --output /tmp/audit.md
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from sqlalchemy import create_engine, text
except ImportError as e:
    sys.exit(f"Missing dependency: {e.name}. Run: pip install sqlalchemy psycopg2-binary")

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

from pii_utils import (
    PERSON_EXPLICIT_MARKERS,
    _CORPORATE_MARKER_RE,
    _PERSON_NAME_TAIL_RE,
    _digits,
    is_person_contractor,
)


def get_engine(db_url: str | None):
    url = db_url or os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL not set and --db-url not provided")
    return create_engine(url, future=True)


def audit(engine, year: int | None) -> dict:
    where = ""
    params = {}
    if year is not None:
        where = "WHERE date >= :start AND date < :end"
        params = {"start": f"{year}-01-01", "end": f"{year + 1}-01-01"}

    with engine.connect() as c:
        total = c.execute(text(f"SELECT COUNT(*) FROM tenders {where}"), params).scalar()
        with_name = c.execute(
            text(f"SELECT COUNT(*) FROM tenders {where + (' AND ' if where else 'WHERE ')} contractor_name IS NOT NULL AND contractor_name != ''"),
            params,
        ).scalar()

        # PESEL-length national IDs
        pesel_where = (where + (" AND " if where else "WHERE ")) + (
            "LENGTH(REGEXP_REPLACE(contractor_national_id, '[^0-9]', '', 'g')) = 11"
        )
        pesel_count = c.execute(text(f"SELECT COUNT(*) FROM tenders {pesel_where}"), params).scalar()

        # Explicit markers in name
        marker_pieces = " OR ".join(
            f"contractor_name ILIKE :m{i}" for i, _ in enumerate(PERSON_EXPLICIT_MARKERS)
        )
        marker_params = {**params, **{f"m{i}": f"%{m}%" for i, m in enumerate(PERSON_EXPLICIT_MARKERS)}}
        explicit_count = c.execute(
            text(f"SELECT COUNT(*) FROM tenders {where + (' AND ' if where else 'WHERE ')} ({marker_pieces})"),
            marker_params,
        ).scalar()

        # Full heuristic count — stream names and apply pii_utils
        total_person = 0
        rule_pesel = 0
        rule_explicit = 0
        rule_tail_name = 0
        sample_names: list[str] = []
        batch = c.execute(
            text(f"""
                SELECT contractor_name, contractor_national_id
                FROM tenders {where}
            """),
            params,
        )
        for name, nid in batch:
            if not is_person_contractor(name, nid):
                continue
            total_person += 1
            digits = _digits(nid)
            if len(digits) == 11:
                rule_pesel += 1
            elif name and any(m in (name or "").lower() for m in PERSON_EXPLICIT_MARKERS):
                rule_explicit += 1
            elif name and _PERSON_NAME_TAIL_RE.search(name.strip()):
                rule_tail_name += 1
            if len(sample_names) < 30 and name:
                sample_names.append(name)

        # Sample of 10 non-anonymized contractor names (sanity check)
        sample_kept = []
        kept_rows = c.execute(
            text(f"SELECT DISTINCT contractor_name, contractor_national_id FROM tenders {where + (' AND ' if where else 'WHERE ')} contractor_name IS NOT NULL LIMIT 5000"),
            params,
        )
        for name, nid in kept_rows:
            if not is_person_contractor(name, nid):
                sample_kept.append(name)
            if len(sample_kept) >= 20:
                break

    return {
        "year": year,
        "total_rows": total,
        "with_contractor_name": with_name,
        "total_person_flagged": total_person,
        "rule_pesel": rule_pesel,
        "rule_explicit_marker": rule_explicit,
        "rule_tail_name": rule_tail_name,
        "pesel_in_db": pesel_count,
        "explicit_marker_in_db": explicit_count,
        "sample_flagged": sample_names,
        "sample_kept": sample_kept,
    }


def render_markdown(result: dict) -> str:
    d = result
    title_scope = f"year {d['year']}" if d["year"] else "full database"
    pct = (d["total_person_flagged"] / d["with_contractor_name"] * 100) if d["with_contractor_name"] else 0.0

    lines = [
        f"# PII Audit — Atlas Przetargów ({title_scope})",
        "",
        f"*Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}*",
        "",
        "## Summary",
        "",
        f"- Total tender rows in scope: **{d['total_rows']:,}**",
        f"- Rows with `contractor_name`: **{d['with_contractor_name']:,}**",
        f"- Rows flagged as natural persons by combined heuristic: **{d['total_person_flagged']:,}** ({pct:.2f}% of those with a name)",
        "",
        "## Detection rules breakdown",
        "",
        "| Rule | Count |",
        "|---|---|",
        f"| PESEL-length national id (11 digits) | {d['rule_pesel']:,} |",
        f"| Explicit CEIDG/sole-proprietor marker in name | {d['rule_explicit_marker']:,} |",
        f"| CEIDG pattern \"Imię Nazwisko\" at end of name | {d['rule_tail_name']:,} |",
        "",
        "Total de-duplicated via OR: same as combined count above.",
        "",
        "## Raw database counts (informational)",
        "",
        f"- PESEL-length `contractor_national_id` rows (all time): {d['pesel_in_db']:,}",
        f"- Contractors with explicit CEIDG markers (all time): {d['explicit_marker_in_db']:,}",
        "",
        "## Sample of FLAGGED names (would be anonymized → `[Osoba fizyczna]`)",
        "",
    ]
    for n in d["sample_flagged"][:30]:
        lines.append(f"- `{n}`")
    lines += [
        "",
        "## Sample of KEPT names (treated as companies — NOT anonymized)",
        "",
    ]
    for n in d["sample_kept"][:20]:
        lines.append(f"- `{n}`")
    lines += [
        "",
        "## Action",
        "",
        "Anonymization is enabled by default in `export.py`. Before public release:",
        "1. Review the flagged sample. If any company slipped in (false positive), expand `CORPORATE_MARKER_WORDS` in `pii_utils.py`.",
        "2. Review the kept sample. If any natural person slipped through (false negative), add a marker or tighten the name pattern.",
        "3. Confirm `ANON_SALT` is set (or `data/.anon_salt` exists) so hashes are stable across releases.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="PII audit for Atlas open-data export")
    parser.add_argument("--year", type=int, help="Limit audit to a single year (e.g. 2024)")
    parser.add_argument("--output", default="PII_AUDIT.md", help="Output markdown path")
    parser.add_argument("--db-url", help="Override DATABASE_URL")
    args = parser.parse_args()

    engine = get_engine(args.db_url)
    print(f"Auditing tenders{(' for ' + str(args.year)) if args.year else ' (full DB)'}...")
    result = audit(engine, args.year)
    md = render_markdown(result)

    out = Path(args.output)
    out.write_text(md, encoding="utf-8")
    print(f"\nWrote {out} ({len(md):,} chars)")
    print(f"Flagged: {result['total_person_flagged']:,} of {result['with_contractor_name']:,} rows with contractor_name")


if __name__ == "__main__":
    main()
