#!/usr/bin/env python3
"""Export Atlas Przetargów tender database to open-data CSV + Parquet dumps.

Usage:
    python export.py --years 2020-2025 --output ./data
    python export.py --years 2024 --output ./data  # single year
    python export.py --all --output ./data          # everything

Outputs per year:
    tenders_YYYY.csv
    tenders_YYYY.parquet

Plus (single file):
    buyers.csv
    contractors.csv
    city_cache.csv

Requires:
    pip install pandas pyarrow sqlalchemy psycopg2-binary
    DATABASE_URL env var (or --db-url flag)

Design notes:
    - Streams per-year to avoid loading 750k rows at once.
    - Drops the `html_body` column (raw notice HTML, often multi-MB).
    - Stringifies JSON columns (`contractors`, `key_attributes`) so they
      survive CSV round-trip; readers can json.loads() them.
    - Fails fast if DATABASE_URL is missing — we never want silent empty dumps.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import pandas as pd
    from sqlalchemy import create_engine, text
except ImportError as e:
    sys.exit(f"Missing dependency: {e.name}. Run: pip install pandas pyarrow sqlalchemy psycopg2-binary")

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

from pii_utils import (
    anonymize_contractor_fields,
    anonymize_contractors_json,
    anonymize_key_attributes,
    get_or_create_salt,
    is_person_contractor,
)


TENDER_COLUMNS = [
    "id", "source", "notice_type", "tender_type", "order_type",
    "title", "buyer", "buyer_nip", "nip_normalized",
    "city", "province", "latitude", "longitude",
    "cpv_code", "date", "publication_date_full", "submitting_offers_date",
    "procedure_result", "estimated_value", "currency",
    "deposit_amount", "offers_count",
    "contractor_name", "contractor_city", "contractor_province",
    "contractor_country", "contractor_national_id", "contractor_count",
    "is_consortium",
    "notice_url", "notice_number", "bzp_number", "ted_number",
    "object_id", "process_id",
    "organization_country", "organization_national_id", "organization_id",
    "client_type", "is_tender_amount_below_eu",
    "is_duplicate", "duplicate_of_id", "created_at",
]

JSON_COLUMNS = {"contractors", "key_attributes", "top_cpv", "trends", "top_partners"}


def get_engine(db_url: str | None):
    url = db_url or os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL not set and --db-url not provided")
    return create_engine(url, future=True)


def _apply_anonymization(df: pd.DataFrame, salt: str) -> tuple[pd.DataFrame, int]:
    """Anonymize contractor_name/national_id for natural persons, walk contractors
    JSON arrays and mask emails/phones in key_attributes. Returns (df, anon_count)."""
    name_col = df.get("contractor_name")
    id_col = df.get("contractor_national_id")
    if name_col is None and id_col is None:
        contractor_mask = pd.Series([False] * len(df))
    else:
        contractor_mask = pd.Series(
            [
                is_person_contractor(n, i)
                for n, i in zip(
                    name_col if name_col is not None else [None] * len(df),
                    id_col if id_col is not None else [None] * len(df),
                )
            ],
            index=df.index,
        )

    anon_count = int(contractor_mask.sum())

    if anon_count:
        anonymized = df.loc[contractor_mask].apply(
            lambda r: anonymize_contractor_fields(
                r.get("contractor_name"), r.get("contractor_national_id"), salt
            ),
            axis=1,
            result_type="expand",
        )
        anonymized.columns = ["contractor_name", "contractor_national_id"]
        df.loc[contractor_mask, ["contractor_name", "contractor_national_id"]] = anonymized.values

    if "contractors" in df.columns:
        df["contractors"] = df["contractors"].apply(
            lambda v: anonymize_contractors_json(v, salt)
        )
    if "key_attributes" in df.columns:
        df["key_attributes"] = df["key_attributes"].apply(
            lambda v: anonymize_key_attributes(v, salt)
        )

    return df, anon_count


def export_tenders_year(
    engine, year: int, out_dir: Path, anonymize: bool, salt: str
) -> tuple[int, int]:
    cols_csv = ", ".join(TENDER_COLUMNS)
    query = text(f"""
        SELECT {cols_csv}
        FROM tenders
        WHERE date >= :start AND date < :end
        ORDER BY date, id
    """)
    df = pd.read_sql(
        query,
        engine,
        params={"start": f"{year}-01-01", "end": f"{year + 1}-01-01"},
    )
    if df.empty:
        print(f"  ({year}) 0 rows — skipping")
        return 0, 0

    anon_count = 0
    if anonymize:
        df, anon_count = _apply_anonymization(df, salt)

    for col in JSON_COLUMNS & set(df.columns):
        df[col] = df[col].apply(lambda v: json.dumps(v, ensure_ascii=False) if v is not None else None)

    csv_path = out_dir / f"tenders_{year}.csv"
    parquet_path = out_dir / f"tenders_{year}.parquet"
    df.to_csv(csv_path, index=False, encoding="utf-8")
    df.to_parquet(parquet_path, index=False, compression="zstd")
    suffix = f" (anonymized {anon_count:,} persons)" if anonymize else ""
    print(f"  ({year}) {len(df):>7,} rows → {csv_path.name} + {parquet_path.name}{suffix}")
    return len(df), anon_count


def export_aggregates(engine, out_dir: Path, anonymize: bool, salt: str) -> None:
    for table in ("buyers", "contractors", "city_cache"):
        df = pd.read_sql(text(f"SELECT * FROM {table}"), engine)
        if df.empty:
            print(f"  {table}: 0 rows — skipping")
            continue

        anon_note = ""
        if anonymize and table == "contractors":
            df, anon_count = _anonymize_contractors_table(df, salt)
            anon_note = f" (anonymized {anon_count:,})"

        for col in JSON_COLUMNS & set(df.columns):
            df[col] = df[col].apply(lambda v: json.dumps(v, ensure_ascii=False) if v is not None else None)
        csv_path = out_dir / f"{table}.csv"
        parquet_path = out_dir / f"{table}.parquet"
        df.to_csv(csv_path, index=False, encoding="utf-8")
        df.to_parquet(parquet_path, index=False, compression="zstd")
        print(f"  {table}: {len(df):>7,} rows → {csv_path.name} + {parquet_path.name}{anon_note}")


def _anonymize_contractors_table(df: pd.DataFrame, salt: str) -> tuple[pd.DataFrame, int]:
    """Apply person-contractor anonymization to the contractors aggregate table.
    Uses the same is_person_contractor rule against name + nip."""
    # Contractors table uses `name` + `nip` (aggregate keys). Fall back gracefully
    # if the schema differs.
    name_col = "name" if "name" in df.columns else None
    id_col = "nip" if "nip" in df.columns else "national_id" if "national_id" in df.columns else None
    if name_col is None or id_col is None:
        return df, 0

    mask = pd.Series(
        [is_person_contractor(n, i) for n, i in zip(df[name_col], df[id_col])],
        index=df.index,
    )
    count = int(mask.sum())
    if count:
        df.loc[mask, name_col] = "[Osoba fizyczna]"
        df.loc[mask, id_col] = df.loc[mask, id_col].apply(
            lambda v: anonymize_contractor_fields("[Osoba fizyczna]", v, salt)[1]
        )
    return df, count


def parse_years(spec: str) -> list[int]:
    if "-" in spec:
        a, b = spec.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(spec)]


def main():
    parser = argparse.ArgumentParser(description="Export Atlas tenders for open-data release")
    parser.add_argument("--years", help='e.g. "2020-2025" or "2024"')
    parser.add_argument("--all", action="store_true", help="Export all years from 2020 to current year")
    parser.add_argument("--output", default="./data", help="Output directory")
    parser.add_argument("--db-url", help="Override DATABASE_URL")
    parser.add_argument("--skip-aggregates", action="store_true", help="Skip buyers/contractors/city_cache dumps")
    parser.add_argument(
        "--no-anonymize",
        action="store_true",
        help="Disable PII anonymization. Only use for local analysis; NEVER for public release.",
    )
    args = parser.parse_args()

    if not args.years and not args.all:
        parser.error("Specify --years or --all")

    import datetime as dt
    years = list(range(2020, dt.date.today().year + 1)) if args.all else parse_years(args.years)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    engine = get_engine(args.db_url)
    anonymize = not args.no_anonymize
    salt = get_or_create_salt() if anonymize else ""

    mode = "with PII anonymization" if anonymize else "RAW (no anonymization — DO NOT PUBLISH)"
    print(f"Exporting tenders for years {years[0]}–{years[-1]} to {out_dir}/ [{mode}]")
    total = 0
    total_anon = 0
    for y in years:
        rows, anon = export_tenders_year(engine, y, out_dir, anonymize, salt)
        total += rows
        total_anon += anon
    print(f"Total tenders exported: {total:,}")
    if anonymize:
        print(f"Total contractor rows anonymized: {total_anon:,}")

    if not args.skip_aggregates:
        print("\nExporting aggregates...")
        export_aggregates(engine, out_dir, anonymize, salt)

    print("\nDone.")


if __name__ == "__main__":
    main()
