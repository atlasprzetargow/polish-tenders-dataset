# Polish Public Tenders Dataset

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19634050.svg)](https://doi.org/10.5281/zenodo.19634050)
[![Kaggle](https://img.shields.io/badge/Kaggle-dataset-20BEFF?logo=kaggle&logoColor=white)](https://www.kaggle.com/datasets/michalpozoga/polish-public-tenders)
[![Data license: CC BY 4.0](https://img.shields.io/badge/data%20license-CC%20BY%204.0-blue.svg)](./LICENSE-DATA)
[![Code license: MIT](https://img.shields.io/badge/code%20license-MIT-green.svg)](./LICENSE-CODE)
[![Release](https://img.shields.io/github/v/release/atlasprzetargow/polish-tenders-dataset?label=release)](https://github.com/atlasprzetargow/polish-tenders-dataset/releases)
[![Records](https://img.shields.io/badge/records-1.4M-0d9488.svg)](#summary)
[![Anonymization](https://img.shields.io/badge/PII-anonymized-brightgreen.svg)](#privacy--anonymization)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](./export.py)
[![Atlas Przetargów](https://img.shields.io/badge/maintained%20by-Atlas%20Przetargów-0d9488.svg)](https://atlasprzetargow.pl)

Open dataset of Polish public procurement notices aggregated from official sources: **BZP** (Biuletyn Zamówień Publicznych, Polish national portal) and **TED** (Tenders Electronic Daily, EU-wide database).

Maintained by [Atlas Przetargów](https://atlasprzetargow.pl) — the Polish public procurement search and analytics platform.

- **Coverage:** 2024 — present (earlier years planned)
- **Records:** ~1.4 million tender notices, ~100 000 buyer profiles, ~80 000 contractor profiles
- **Update cadence:** quarterly (full dump per release)
- **Format:** CSV (UTF-8) + Parquet
- **License:** [CC BY 4.0](./LICENSE-DATA) for data, [MIT](./LICENSE-CODE) for code
- **Privacy:** Natural-person contractors (sole proprietors) are anonymized — see [Privacy & anonymization](#privacy--anonymization) below.

---

## Contents

```
data/
  tenders_YYYY.csv          # Yearly tender dumps
  tenders_YYYY.parquet      # Same, columnar format (recommended for analytics)
  buyers.csv                # Aggregated buyer profiles (by NIP)
  contractors.csv           # Aggregated contractor profiles (by NIP, anonymized for natural persons)
  city_cache.csv            # City name → lat/lng/province mapping
schema/
  tenders.md                # Column descriptions for tenders
  buyers.md
  contractors.md
export.py                   # Regenerate data from Atlas Przetargów database
audit_pii.py                # PII audit report generator
pii_utils.py                # PII detection + anonymization (used by export.py)
publish.sh                  # Publish to GitHub + Kaggle + Zenodo
LICENSE-DATA                # CC BY 4.0 (for data)
LICENSE-CODE                # MIT (for code)
```

## Quick start

For a full runnable tour — including a bar chart of top CPV divisions, a Herfindahl-Hirschman market-concentration calculation, and a DuckDB-over-HTTP example — see [`notebooks/01_getting_started.ipynb`](./notebooks/01_getting_started.ipynb). Rendered directly by GitHub, no local setup needed to preview.

### Pandas

```python
import pandas as pd

tenders = pd.read_parquet("data/tenders_2024.parquet")
print(f"{len(tenders):,} tenders in 2024")
print(tenders.groupby("province")["estimated_value"].sum().sort_values(ascending=False).head())
```

### SQL (DuckDB)

```sql
SELECT province, COUNT(*) AS n, SUM(estimated_value) AS total_value
FROM 'data/tenders_2024.parquet'
WHERE notice_type LIKE 'Contract%'
GROUP BY province
ORDER BY total_value DESC;
```

## Schema highlights

| Column | Type | Description |
|---|---|---|
| `id` | string | BZP or TED notice number (primary key) |
| `title` | string | Tender title |
| `buyer` | string | Contracting authority name |
| `buyer_nip` | string | Polish tax ID (10 digits) |
| `city`, `province` | string | Location; province uses `PLxx` codes (NUTS-2 compatible) |
| `cpv_code` | string | Comma-separated CPV codes (EU procurement vocabulary) |
| `notice_type` | string | `ContractNotice`, `TenderResultNotice`, `cn-standard` (TED), etc. |
| `order_type` | string | `Roboty budowlane` / `Dostawy` / `Usługi` |
| `date` | date | Publication date |
| `submitting_offers_date` | timestamp | Deadline for offer submission |
| `estimated_value` | float | Estimated contract value (in `currency`) |
| `currency` | string | Usually `PLN` or `EUR` (TED) |
| `source` | string | `bzp` or `ted` |
| `is_duplicate` | bool | TED duplicates of BZP entries (filter these out for deduplicated analyses) |
| `contractor_name`, `contractor_national_id` | string | Winner (only on `TenderResultNotice`) |
| `latitude`, `longitude` | float | Geocoded coordinates of buyer's city |

Full schema: [`schema/tenders.md`](./schema/tenders.md).

## Typical use cases

- **Market analysis** — which provinces/cities issue most tenders, by sector (CPV)
- **Buyer/contractor profiling** — who wins what, from whom, for how much
- **Academic research** — public procurement economics, competition, pricing
- **NLP** — Polish-language tender titles and specifications (large corpus)
- **ML baselines** — classification (CPV prediction), value estimation, winner prediction

## Attribution

If you use this dataset, please cite it. A machine-readable [`CITATION.cff`](./CITATION.cff) is included so GitHub, Zenodo, and reference managers (Zotero, Mendeley) can import the citation automatically.

Human-readable citation:

> Atlas Przetargów (2026). *Polish Public Tenders Dataset (BZP + TED)*, version 2026.Q2. <https://github.com/atlasprzetargow/polish-tenders-dataset>

Or, if using the Zenodo-archived version (stable DOI, preferred for academic citations):

> Atlas Przetargów (2026). *Polish Public Tenders Dataset (BZP + TED) — 2026.Q2*. Zenodo. https://doi.org/10.5281/zenodo.19634050

## Data sources

Data is aggregated from official public sources:

- **BZP** (ezamowienia.gov.pl) — Polish national procurement portal, run by UZP
- **TED** (ted.europa.eu) — EU-wide procurement database, run by the Publications Office of the EU

This dataset adds on top of the raw sources:

- **Deduplication** — TED notices that duplicate BZP entries are flagged (`is_duplicate = true`)
- **Geocoding** — cities resolved to lat/lng
- **Normalization** — province codes standardized to `PLxx`, NIPs cleaned
- **Aggregation** — per-buyer and per-contractor profiles with totals and trends
- **Anonymization** — natural-person contractors (CEIDG sole proprietors, PESEL holders) are anonymized; see below

## Privacy & anonymization

Polish public procurement contract-award data is, by law, public: Article 269 of the Polish Public Procurement Act (PZP) mandates publication of contractor names and NIPs in the BZP bulletin, and the EU Open Data Directive 2019/1024 actively encourages re-use of procurement data. Aggregator platforms (eGospodarka, Oferent, Bazhub, etc.) have been republishing this data for over a decade without anonymization; the Polish Data Protection Authority (UODO) has taken no enforcement action. **No anonymization is legally required**, either for buyers or contractors.

That said, bulk redistribution of 1.4M records under a CC BY license — downloadable by any crawler — differs qualitatively from per-query lookups on a website. As a **precautionary measure**, we additionally anonymize contractor rows where our heuristic classifies the winner as a natural person. This is optional, not GDPR-mandated. Rules applied:

- `contractor_national_id` is 11 digits long (PESEL — Polish personal identifier; companies use 10-digit NIPs)
- `contractor_name` contains explicit markers such as *"osoba fizyczna"*, *"jednoosobowa działalność"*, *"prowadzący działalność"*, or *CEIDG*
- `contractor_name` ends with a *"Imię Nazwisko"* pattern AND the first-name token matches a curated list of ~250 Polish given names (eliminates false positives for foreign corporate names)

When any of the above match, the row is transformed as follows:

| Field | Before | After |
|---|---|---|
| `contractor_name` | `"ABC Firma Usługowa Jan Kowalski"` | `"[Osoba fizyczna]"` |
| `contractor_national_id` | `"9876543210"` | `"anon-a1b2c3d4e5"` (stable SHA-256 hash, salted) |
| `contractor_city` | `"Kraków"` | *kept — city-level aggregation still works* |
| `contractor_province` | `"PL21"` | *kept* |
| `contractors` (JSON) | per-entry with name+ID | per-entry anonymized with the same rules |

The hash is stable across releases (same input → same output) but irreversible without the salt. This preserves cross-year joins and contractor-level analytics while removing identifying information.

**Buyer side is NOT anonymized.** Polish public-procurement buyers are, by law, public bodies or publicly-registered entities; there are zero PESEL-length IDs in the `buyer_nip` column.

Coverage statistics (2024 sample): 59,472 of 238,103 rows with a contractor name (~25%) are anonymized under the above rules. The anonymization code is open-source under MIT in [`pii_utils.py`](./pii_utils.py) and [`audit_pii.py`](./audit_pii.py). If you believe a row has been mis-classified (false positive or negative), please open an issue with the tender `id`.

## Regenerating the dataset

```bash
# From the Atlas Przetargów monorepo
cd open-data
python export.py --years 2020-2025 --output ./data
```

Requires:
- Python 3.11+, `pandas`, `pyarrow`, `sqlalchemy`, `psycopg2-binary`
- Access to the Atlas Przetargów database (env var `DATABASE_URL`)

Public contributors cannot regenerate — the full DB is not public. But the output CSVs are open under CC BY 4.0.

## Contributing

- **Issues** — found a data quality problem? Open an issue with the tender `id`.
- **Schema suggestions** — PRs welcome on `schema/` docs.
- **Code** — `export.py` and `publish.sh` are MIT-licensed; PRs for better formatting, additional derived columns, etc. welcome.

## Mirrors and citations

The same dataset is mirrored on Zenodo (for stable DOI / academic citation) and Kaggle (for ML / notebook discoverability):

- **Zenodo:** [`10.5281/zenodo.19634050`](https://doi.org/10.5281/zenodo.19634050) (versioned) · concept DOI: [`10.5281/zenodo.19634049`](https://doi.org/10.5281/zenodo.19634049) (resolves to latest version)
- **Kaggle:** [`michalpozoga/polish-public-tenders`](https://www.kaggle.com/datasets/michalpozoga/polish-public-tenders) — same files, plus discoverable through Kaggle's notebook search
- **GitHub** (this repo) — primary source, with full source code, schema docs, and the getting-started notebook

## Related

- **Atlas Przetargów** — search UI: <https://atlasprzetargow.pl>
- **MCP Server** — `@atlasprzetargow/mcp` on npm — query this data from Claude/Cursor
- **REST API** — <https://atlasprzetargow.pl/api/tenders>
- **Launch blog post** (methodology details) — <https://atlasprzetargow.pl/blog/open-data-polskich-przetargow-2024-2025>

## Changelog

- **v2026.Q2 (2026-04-17)** — Initial public release. Coverage 2024 — present (~1.4M tender notices). PII anonymization enabled for all natural-person contractors.
