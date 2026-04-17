# Schema: `contractors.csv`

Aggregated profiles of contractors (tender winners). One row per NIP.

| Column | Type | Null | Description |
|---|---|---|---|
| `nip` | string | no | Primary key. 10-digit Polish tax ID (or foreign equivalent for TED). **For natural persons, replaced with `"anon-"` + 10-char SHA-256 hash** (see [Anonymization](#anonymization)). |
| `name` | string | yes | Contractor name. **Replaced with `"[Osoba fizyczna]"` when the contractor is a natural person** (see [Anonymization](#anonymization)). |
| `city` | string | yes | Registered city. |
| `province` | string | yes | `PLxx` code. |
| `country` | string | yes | Country code (default `PL` for BZP). |
| `total_wins` | integer | no | Total tenders won. |
| `total_value` | decimal | no | Sum of awarded values. |
| `avg_win_value` | decimal | no | Mean awarded value. |
| `win_rate` | float | yes | Share of bids won (where offer-count data is available; often null). |
| `top_cpv` | JSON | yes | Top 5 CPV divisions: `[{"cpv": "45", "count": 12}, ...]`. |
| `trends` | JSON | yes | Yearly: `{"2024": {"wins": 8, "value": 2000000}, ...}`. |
| `top_partners` | JSON | yes | Top buyers this contractor wins from: `[{"nip": "...", "name": "...", "wins": 5}, ...]`. |
| `first_win_date` | date | yes | Earliest win. |
| `last_win_date` | date | yes | Most recent win. |
| `updated_at` | timestamp | no | Last refresh. |

## Joining with tender results

```python
results = tenders[tenders["notice_type"].isin(["TenderResultNotice", "ContractAwardNotice", "can-standard"])]
joined = results.merge(contractors, left_on="contractor_national_id", right_on="nip", how="left", suffixes=("", "_contractor"))
```

## Consortium handling

- Rows with multiple contractors (`is_consortium = true`) in `tenders_*.csv` only expose the **first** contractor's NIP in `contractor_national_id`.
- For full consortium membership, use the `contractors` JSON field in the Atlas API (`/api/tenders/<id>`).
- `contractors.csv` aggregates wins regardless of consortium position (each consortium member gets credited).

## Anonymization

Natural-person contractors (CEIDG sole proprietors, PESEL holders) are anonymized to comply with Polish/EU data protection law. Anonymized rows have:
- `name` = `"[Osoba fizyczna]"`
- `nip` = `"anon-"` + 10-char SHA-256 hash (stable across releases with the same salt; irreversible)

Aggregates (`total_wins`, `total_value`, `trends`, etc.) are preserved per anonymized identity, so cross-year analytics at the anonymized-person level still work. See [`../schema/tenders.md#anonymization`](./tenders.md#anonymization) for the full detection rules.
