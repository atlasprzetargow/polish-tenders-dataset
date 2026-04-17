# Schema: `tenders_YYYY.csv`

Each row is one public procurement notice. A single "procedure" may have multiple rows (one for the contract notice, another for the award result) — link them via `process_id`.

| Column | Type | Null | Description |
|---|---|---|---|
| `id` | string | no | Primary key. BZP notice number (e.g. `2024/BZP 00123456/01`) or TED number (e.g. `123456-2024`). |
| `source` | string | no | `bzp` or `ted`. |
| `notice_type` | string | yes | BZP: `ContractNotice`, `TenderResultNotice`, `ContractAwardNotice`, `ContestNotice`. TED: `cn-standard`, `can-standard`, `cn-desg`, `pin-*`, etc. |
| `tender_type` | string | yes | Procedure type (BZP: `Przetarg nieograniczony`, `Tryb podstawowy`, etc.). |
| `order_type` | string | yes | `Roboty budowlane` / `Dostawy` / `Usługi`. |
| `title` | string | yes | Tender title as published. |
| `buyer` | string | yes | Contracting authority name. |
| `buyer_nip` | string | yes | Polish tax ID, 10 digits, dashes stripped. Foreign key to `buyers.csv`. |
| `nip_normalized` | string | yes | Same as `buyer_nip` but guaranteed clean (no spaces, no dashes, no leading zeros dropped). Use this for joins. |
| `city` | string | yes | Buyer's city (or tender location). |
| `province` | string | yes | `PLxx` code (NUTS-2). See [province codes](#province-codes) below. |
| `latitude` | float | yes | Geocoded latitude of `city`. |
| `longitude` | float | yes | Geocoded longitude of `city`. |
| `cpv_code` | string | yes | Comma-separated CPV codes (EU procurement vocabulary, 8-digit). First code is primary. Example: `45000000-7,45210000-2`. |
| `date` | date | yes | Publication date (YYYY-MM-DD). |
| `publication_date_full` | string | yes | Full timestamp string as published. |
| `submitting_offers_date` | timestamp | yes | Deadline for offer submission (ISO 8601). |
| `procedure_result` | string | yes | On `TenderResultNotice`: e.g. `Wybrano ofertę`, `Unieważniono postępowanie`. |
| `estimated_value` | float | yes | Estimated or awarded value in `currency`. |
| `currency` | string | yes | Usually `PLN` (BZP) or `EUR` (TED). |
| `deposit_amount` | decimal | yes | Wadium (bid deposit) in `currency`. |
| `offers_count` | integer | yes | Number of offers submitted (populated on result notices). |
| `contractor_name` | string | yes | Winner name (on result notices). **Anonymized to `"[Osoba fizyczna]"` when the winner is a natural person** (CEIDG sole proprietor, PESEL holder) — see [Anonymization](#anonymization) below. |
| `contractor_city` | string | yes | Winner's city. Not anonymized. |
| `contractor_province` | string | yes | Winner's province. Not anonymized. |
| `contractor_country` | string | yes | Winner's country (TED only, BZP assumed PL). |
| `contractor_national_id` | string | yes | Winner's NIP (10 digits) or REGON. **For natural persons, replaced with `"anon-"` + 10-char SHA-256 hash** — see [Anonymization](#anonymization). Foreign key to `contractors.csv`. |
| `contractor_count` | integer | yes | Number of winners (>1 means consortium). |
| `is_consortium` | bool | no | True if multiple contractors won together. |
| `notice_url` | string | yes | URL of the original notice at source. |
| `notice_number` | string | yes | Human-readable notice number (BZP). |
| `bzp_number` | string | yes | BZP publication number. |
| `ted_number` | string | yes | TED publication number (e.g. `123456-2024`). |
| `object_id` | string | yes | BZP internal object ID. |
| `process_id` | string | yes | OCDS tenderId — use this to link a contract notice with its award result. |
| `organization_country` | string | yes | Buyer country (usually `PL`, TED may have `DE/FR/...` for cross-border notices). |
| `organization_national_id` | string | yes | Buyer's NIP (duplicate of `buyer_nip` for some records). |
| `organization_id` | string | yes | Buyer's internal ID in source system. |
| `client_type` | string | yes | Type of contracting authority (e.g. `JSFP` — unit of public finance sector). |
| `is_tender_amount_below_eu` | bool | yes | Whether value is below EU threshold. |
| `is_duplicate` | bool | no | TED notice that duplicates a BZP entry. Filter `is_duplicate = false` for deduplicated analyses. |
| `duplicate_of_id` | string | yes | If `is_duplicate = true`, the BZP `id` this duplicates. |
| `created_at` | timestamp | no | When the row was ingested into Atlas (not the publication date). |

## Excluded columns

To keep CSVs usable:
- `html_body` — raw HTML body of the notice (can be several MB per row). Not included. Available via Atlas API if needed.
- `key_attributes` JSON — extracted structured attributes. Flattened into top-level columns where sensible.
- `contractors` JSON — for consortium notices with >1 contractor, only the first is included in `contractor_*` columns. Full list in the Atlas API.

## Anonymization

Under Polish/EU data-protection law (RODO/GDPR), we cannot publish identifying data for natural persons under an open license. The following contractor rows are anonymized before release:

1. `contractor_national_id` is 11 digits long (PESEL — personal identifier; companies use 10-digit NIP)
2. `contractor_name` contains explicit markers: *"osoba fizyczna"*, *"jednoosobowa działalność"*, *"prowadzący działalność"*, *CEIDG*
3. `contractor_name` ends with a *"Imię Nazwisko"* pattern where the first word matches a curated list of ~250 Polish given names — catches sole-proprietor naming patterns like `"PHUP DELTABUD Krzysztof Łakomiec"` and `"Firma Usługowa Danuta Frymark"` without flagging English corporate names like `"Roche Diagnostics Polska"`

When any rule matches:
- `contractor_name` → `"[Osoba fizyczna]"`
- `contractor_national_id` → `"anon-" + first 10 hex chars of SHA-256(salt + original_id)` (stable across releases, irreversible without the salt)
- `contractor_city` / `contractor_province` / `contractor_country` are kept (geographic aggregates still work)

Detection and anonymization code: [`pii_utils.py`](../pii_utils.py). Audit report with counts and samples: run `python audit_pii.py --year YYYY`.

**Buyer columns are NOT anonymized.** Polish public-procurement buyers are, by law, public bodies or publicly-registered entities; the dataset contains zero PESEL-length `buyer_nip` values.

## Province codes

| Code | Voivodeship |
|---|---|
| PL11 | Łódzkie |
| PL12 | Mazowieckie |
| PL21 | Małopolskie |
| PL22 | Śląskie |
| PL31 | Lubelskie |
| PL32 | Podkarpackie |
| PL33 | Świętokrzyskie |
| PL34 | Podlaskie |
| PL41 | Wielkopolskie |
| PL42 | Zachodniopomorskie |
| PL43 | Lubuskie |
| PL51 | Dolnośląskie |
| PL52 | Opolskie |
| PL61 | Kujawsko-Pomorskie |
| PL62 | Warmińsko-Mazurskie |
| PL63 | Pomorskie |
| PL71 | (deprecated — merged into PL11) |
| PL72 | (deprecated — merged into PL33) |

Codes are NUTS-2 compatible but Atlas stores them without the NUTS prefix.

## Notice types

### BZP
- `ContractNotice` — opening of a tender procedure (most important for active-tender tracking)
- `ContractAwardNotice` / `TenderResultNotice` — contract award result
- `ContestNotice` — design contest
- `ConcessionNotice` — concession contract

### TED (2024+ eForms)
- `cn-standard` — contract notice (opening)
- `can-standard` — contract award notice
- `cn-desg` — design contest
- `pin-*` — prior information notice

To match BZP's "active tender" semantics, filter: `notice_type IN ('ContractNotice', 'cn-standard') AND submitting_offers_date > NOW()`.

## CPV codes

CPV (Common Procurement Vocabulary) is the EU-wide classification for procurement. Format: `XXXXXXXX-Y` where the first 2 digits are the division:

- `03` — Agriculture, farming
- `09` — Petroleum, electricity, fuels
- `14` — Mining, metals
- `15` — Food, beverages, tobacco
- `18` — Clothing, footwear
- `22` — Printed matter
- `24` — Chemical products
- `30` — Office, computing equipment
- `31` — Electrical machinery
- `32` — Radio, TV, communications
- `33` — Medical equipment, pharmaceuticals
- `34` — Transport equipment
- `35` — Security, firefighting, defense
- `37` — Musical instruments, sports
- `38` — Laboratory, optical, precision
- `39` — Furniture, furnishings
- `41` — Water
- `42` — Industrial machinery
- `43` — Mining machinery
- `44` — Construction materials, structures
- `45` — Construction works
- `48` — Software packages, IT systems
- `50` — Repair, maintenance
- `51` — Installation services
- `55` — Hotel, restaurant, retail
- `60` — Transport services
- `63` — Supporting transport services, travel
- `64` — Postal, telecommunications
- `65` — Public utilities
- `66` — Financial, insurance services
- `70` — Real estate services
- `71` — Architectural, engineering services
- `72` — IT services
- `73` — R&D services
- `75` — Administration, defense, social services
- `76` — Oil, gas services
- `77` — Agricultural, forestry services
- `79` — Business services
- `80` — Education, training
- `85` — Health, social work
- `90` — Sewage, refuse, cleaning
- `92` — Recreation, culture, sport
- `98` — Other community services

Full list: <https://simap.ted.europa.eu/cpv>.
