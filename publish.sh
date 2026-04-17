#!/usr/bin/env bash
# Publish the dataset to GitHub + Kaggle + Zenodo.
#
# Requires:
#   - gh CLI authenticated (gh auth login)
#   - kaggle CLI installed, ~/.kaggle/kaggle.json present
#   - ZENODO_TOKEN env var
#
# Pre-flight: run `python export.py --all --output ./data` first.

set -euo pipefail

DATA_DIR="${DATA_DIR:-./data}"
REPO_OWNER="${REPO_OWNER:-atlasprzetargow}"
REPO_NAME="${REPO_NAME:-polish-tenders-dataset}"
KAGGLE_SLUG="${KAGGLE_SLUG:-atlasprzetargow/polish-public-tenders}"
VERSION="${VERSION:-$(date +%Y.%m)}"

if [[ ! -d "$DATA_DIR" ]] || [[ -z "$(ls -A "$DATA_DIR" 2>/dev/null)" ]]; then
    echo "ERROR: $DATA_DIR is empty. Run: python export.py --all --output $DATA_DIR" >&2
    exit 1
fi

cmd="${1:-all}"

publish_github() {
    echo "== GitHub =="
    if ! gh repo view "${REPO_OWNER}/${REPO_NAME}" &>/dev/null; then
        echo "Creating repo ${REPO_OWNER}/${REPO_NAME}..."
        gh repo create "${REPO_OWNER}/${REPO_NAME}" --public \
            --description "Open dataset of Polish public procurement notices (BZP + TED). Maintained by Atlas Przetargów." \
            --homepage "https://atlasprzetargow.pl"
    fi

    # Split strategy: Parquet files + small aggregates + code/docs are committed to
    # git (browsable on GitHub, fits well under the 100 MB/file limit). The raw
    # CSVs are uploaded as release assets (gzipped) since they're too large for
    # git but perfect for ad-hoc downloads.
    local tmpdir release_dir
    tmpdir=$(mktemp -d)
    release_dir=$(mktemp -d)

    # 1) Prepare the git repo: copy only parquet data + code + docs
    mkdir -p "$tmpdir/data"
    cp "$DATA_DIR"/*.parquet "$tmpdir/data/" 2>/dev/null || true
    cp "$DATA_DIR"/city_cache.csv "$tmpdir/data/" 2>/dev/null || true
    cp "$DATA_DIR"/contractors.csv "$tmpdir/data/" 2>/dev/null || true
    touch "$tmpdir/data/.gitkeep"
    cp -r README.md schema/ LICENSE-DATA LICENSE-CODE export.py audit_pii.py pii_utils.py publish.sh .gitignore "$tmpdir/"

    # 2) Prepare release assets: gzip the large CSVs
    for csv in "$DATA_DIR"/tenders_*.csv "$DATA_DIR"/buyers.csv; do
        [[ -f "$csv" ]] || continue
        local base
        base=$(basename "$csv")
        gzip -c "$csv" > "$release_dir/${base}.gz"
    done

    (
        cd "$tmpdir"
        git init -q -b main
        git add .
        git commit -q -m "Release ${VERSION}"
        git remote add origin "https://github.com/${REPO_OWNER}/${REPO_NAME}.git"
        git push -uf origin main

        # Release with CSV.gz assets attached
        local asset_args=()
        for f in "$release_dir"/*.gz; do
            asset_args+=("$f")
        done
        local notes
        notes="Quarterly dataset release.\n\n**Git-tracked** (browsable): Parquet dumps + aggregates (contractors, city_cache).\n**Release assets** (below): Gzipped CSV versions for users who prefer CSV.\n\nFiles: $(ls "$DATA_DIR"/tenders_*.parquet 2>/dev/null | wc -l) yearly parquets, $(ls "$release_dir"/*.gz 2>/dev/null | wc -l) CSV.gz release assets."
        gh release create "v${VERSION}" --title "Polish Tenders Dataset ${VERSION}" \
            --notes "$(printf "%b" "$notes")" "${asset_args[@]}"
    )
    rm -rf "$tmpdir" "$release_dir"
}

publish_kaggle() {
    echo "== Kaggle =="
    if ! command -v kaggle &>/dev/null; then
        echo "ERROR: kaggle CLI not installed. Run: pip install kaggle" >&2
        exit 1
    fi
    if [[ ! -f "${HOME}/.kaggle/kaggle.json" ]]; then
        echo "ERROR: ~/.kaggle/kaggle.json missing. Create token at https://www.kaggle.com/settings/account" >&2
        exit 1
    fi

    local tmpdir
    tmpdir=$(mktemp -d)
    # Kaggle wants a flat directory. Use parquet + CSV for broad compatibility.
    cp "$DATA_DIR"/*.parquet "$tmpdir/" 2>/dev/null || true
    cp "$DATA_DIR"/*.csv "$tmpdir/" 2>/dev/null || true

    cat > "$tmpdir/dataset-metadata.json" <<EOF
{
  "title": "Polish Public Tenders Dataset (BZP + TED)",
  "id": "${KAGGLE_SLUG}",
  "licenses": [{"name": "CC-BY-4.0"}],
  "keywords": ["procurement", "poland", "tenders", "government", "public-sector", "bzp", "ted", "nuts-2", "cpv", "open-data", "transparency", "eu"],
  "subtitle": "~1.4M Polish public procurement notices aggregated from BZP + TED (2024-present)",
  "description": "Open dataset of Polish public procurement notices aggregated from BZP (Biuletyn Zamowien Publicznych, Polish national procurement bulletin) and TED (Tenders Electronic Daily, EU-wide procurement database). Covers 2024 onward — ~1.4M tender notices, ~23k buyer profiles, ~82k contractor profiles. Natural-person contractors (sole proprietors) are anonymized via a stable salted SHA-256 hash to comply with Polish/EU data protection law. Full schema docs, a getting-started notebook (with HHI market-concentration analysis), and open-source anonymization code are available in the source repository: https://github.com/${REPO_OWNER}/${REPO_NAME}"
}
EOF

    if kaggle datasets status "$KAGGLE_SLUG" &>/dev/null; then
        echo "Updating existing Kaggle dataset..."
        kaggle datasets version -p "$tmpdir" -m "Release ${VERSION}" --dir-mode zip
    else
        echo "Creating new Kaggle dataset..."
        kaggle datasets create -p "$tmpdir" --dir-mode zip --public
    fi
    rm -rf "$tmpdir"
}

publish_zenodo() {
    echo "== Zenodo =="
    : "${ZENODO_TOKEN:?ZENODO_TOKEN not set. Generate at https://zenodo.org/account/settings/applications/tokens/new/ with scopes: deposit:write, deposit:actions}"

    local api="${ZENODO_SANDBOX:+https://sandbox.zenodo.org/api}"
    api="${api:-https://zenodo.org/api}"

    local concept_file="${HOME}/.config/atlas-zenodo-concept.txt"
    local concept_id=""
    if [[ -f "$concept_file" ]]; then
        concept_id=$(cat "$concept_file")
        echo "Using existing concept_id=${concept_id} — will create a new version."
    fi

    local metadata_json
    metadata_json=$(cat <<EOF
{
  "metadata": {
    "title": "Polish Public Tenders Dataset (BZP + TED) — ${VERSION}",
    "upload_type": "dataset",
    "description": "<p>Open dataset of Polish public procurement notices aggregated from official sources: <strong>BZP</strong> (Biuletyn Zam&oacute;wień Publicznych, the Polish national procurement bulletin) and <strong>TED</strong> (Tenders Electronic Daily, the EU-wide procurement database).</p><p><strong>Coverage:</strong> 2024 onward, ~1.4 million tender notices, ~23k buyer profiles, ~82k contractor profiles.</p><p><strong>Methodology:</strong> BZP is ingested via the OCDS (Open Contracting Data Standard) JSON API; TED via its eForms XML feed. TED notices that duplicate a BZP entry are flagged via <code>is_duplicate</code>. Cities are geocoded; provinces normalized to NUTS-2 codes; NIPs (Polish tax IDs) normalized to the canonical 10-digit form.</p><p><strong>Anonymization:</strong> natural-person contractors (CEIDG sole proprietors, PESEL holders) are anonymized via a stable salted SHA-256 hash to comply with Polish/EU data-protection law. Buyers are not anonymized — they are, by law, public bodies.</p><p>Source code, schema documentation, a getting-started notebook, and the anonymization code (MIT-licensed) are available on GitHub: <a href='https://github.com/${REPO_OWNER}/${REPO_NAME}'>github.com/${REPO_OWNER}/${REPO_NAME}</a>.</p>",
    "creators": [
      {"name": "Atlas Przetarg\u00f3w", "affiliation": "atlasprzetargow.pl"}
    ],
    "keywords": ["public procurement", "Poland", "BZP", "TED", "OCDS", "eForms", "NUTS-2", "CPV", "open data", "government contracts", "transparency"],
    "license": "cc-by-4.0",
    "access_right": "open",
    "language": "pol",
    "related_identifiers": [
      {"identifier": "https://github.com/${REPO_OWNER}/${REPO_NAME}", "relation": "isSupplementTo", "resource_type": "software"},
      {"identifier": "https://atlasprzetargow.pl/blog/open-data-polskich-przetargow-2024-2025", "relation": "isDescribedBy", "resource_type": "publication-article"}
    ],
    "version": "${VERSION}",
    "notes": "Machine-readable citation is also available as CITATION.cff in the GitHub repository."
  }
}
EOF
)

    local deposit_json deposit_id bucket_url
    if [[ -n "$concept_id" ]]; then
        # New version of existing record
        deposit_json=$(curl -sf -X POST "${api}/deposit/depositions/${concept_id}/actions/newversion?access_token=${ZENODO_TOKEN}")
        deposit_id=$(echo "$deposit_json" | jq -r '.links.latest_draft' | awk -F/ '{print $NF}')
        deposit_json=$(curl -sf "${api}/deposit/depositions/${deposit_id}?access_token=${ZENODO_TOKEN}")
    else
        # Brand-new deposition
        deposit_json=$(curl -sf -X POST -H "Content-Type: application/json" -d '{}' \
            "${api}/deposit/depositions?access_token=${ZENODO_TOKEN}")
        deposit_id=$(echo "$deposit_json" | jq -r '.id')
        echo "New deposition created: id=${deposit_id}"
    fi
    bucket_url=$(echo "$deposit_json" | jq -r '.links.bucket')
    if [[ -z "$bucket_url" || "$bucket_url" == "null" ]]; then
        echo "ERROR: could not obtain bucket URL. Deposition response:" >&2
        echo "$deposit_json" >&2
        exit 1
    fi

    # Upload files: parquet + docs + notebook + CSVs
    local tmpup
    tmpup=$(mktemp -d)
    cp "$DATA_DIR"/*.parquet "$tmpup/" 2>/dev/null || true
    cp "$DATA_DIR"/*.csv "$tmpup/" 2>/dev/null || true
    # Include README + schema + notebook + CITATION for archival completeness
    [[ -f README.md ]] && cp README.md "$tmpup/"
    [[ -f CITATION.cff ]] && cp CITATION.cff "$tmpup/"
    [[ -d schema ]] && tar czf "$tmpup/schema.tar.gz" schema/
    [[ -d notebooks ]] && tar czf "$tmpup/notebooks.tar.gz" notebooks/

    for f in "$tmpup"/*; do
        local fname
        fname=$(basename "$f")
        echo "  uploading ${fname} ($(du -h "$f" | cut -f1))"
        curl -sf --upload-file "$f" "${bucket_url}/${fname}?access_token=${ZENODO_TOKEN}" >/dev/null
    done

    # Set metadata
    echo "  setting metadata"
    curl -sf -X PUT -H "Content-Type: application/json" -d "$metadata_json" \
        "${api}/deposit/depositions/${deposit_id}?access_token=${ZENODO_TOKEN}" >/dev/null

    # Publish
    echo "  publishing"
    local publish_resp
    publish_resp=$(curl -sf -X POST \
        "${api}/deposit/depositions/${deposit_id}/actions/publish?access_token=${ZENODO_TOKEN}")
    local doi concept
    doi=$(echo "$publish_resp" | jq -r '.doi')
    concept=$(echo "$publish_resp" | jq -r '.conceptrecid // empty')

    if [[ -n "$concept" && ! -f "$concept_file" ]]; then
        mkdir -p "$(dirname "$concept_file")"
        echo "$concept" > "$concept_file"
        echo "  saved concept_id=${concept} to ${concept_file} (used for future versions)"
    fi

    echo "Published: DOI=${doi}"
    echo "URL: https://doi.org/${doi}"
    rm -rf "$tmpup"
}

case "$cmd" in
    github) publish_github ;;
    kaggle) publish_kaggle ;;
    zenodo) publish_zenodo ;;
    all)
        publish_github
        publish_kaggle
        publish_zenodo
        ;;
    *)
        echo "Usage: $0 {github|kaggle|zenodo|all}" >&2
        exit 1
        ;;
esac

echo "Done."
