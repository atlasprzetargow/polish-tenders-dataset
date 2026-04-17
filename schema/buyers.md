# Schema: `buyers.csv`

Aggregated profiles of contracting authorities (buyers). One row per NIP.

| Column | Type | Null | Description |
|---|---|---|---|
| `nip` | string | no | Primary key. 10-digit Polish tax ID. |
| `name` | string | yes | Buyer name (most common spelling across tenders). |
| `city` | string | yes | Buyer's registered city. |
| `province` | string | yes | `PLxx` code. |
| `total_tenders` | integer | no | Total tenders issued (all notice types). |
| `total_results` | integer | no | Total result/award notices. |
| `total_value` | decimal | no | Sum of `estimated_value` across all tenders (PLN-equivalent, TED EUR values are not converted). |
| `avg_value` | decimal | no | Mean `estimated_value`. |
| `top_cpv` | JSON | yes | Top 5 CPV divisions with counts: `[{"cpv": "45", "count": 123}, ...]`. |
| `trends` | JSON | yes | Yearly buckets: `{"2024": {"count": 42, "value": 1500000}, ...}`. |
| `top_partners` | JSON | yes | Top contractors (by wins from this buyer): `[{"nip": "...", "name": "...", "wins": 12}, ...]`. |
| `first_tender_date` | date | yes | Earliest tender date in our data. |
| `last_tender_date` | date | yes | Most recent tender date. |
| `updated_at` | timestamp | no | When this aggregation was last refreshed. |

## Joining with tenders

```python
import pandas as pd

tenders = pd.read_parquet("data/tenders_2024.parquet")
buyers = pd.read_csv("data/buyers.csv")

merged = tenders.merge(buyers, left_on="buyer_nip", right_on="nip", how="left", suffixes=("", "_buyer"))
```

## Known caveats

- **Name collisions**: smaller buyers sometimes lack a proper NIP in source data; rows without `buyer_nip` are not aggregated into `buyers.csv`.
- **Province reassignments**: if a buyer moves HQ, older tenders keep the old province.
- **Value sums across currencies**: TED tenders may use EUR. `total_value` sums the raw numbers without FX conversion. Use with care on mixed-source buyers.
