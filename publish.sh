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

    local tmpdir
    tmpdir=$(mktemp -d)
    cp -r "$DATA_DIR"/* "$tmpdir/"
    cat > "$tmpdir/dataset-metadata.json" <<EOF
{
  "title": "Polish Public Tenders 2020-2025 (BZP + TED)",
  "id": "${KAGGLE_SLUG}",
  "licenses": [{"name": "CC-BY-4.0"}],
  "keywords": ["procurement", "poland", "tenders", "government", "public-sector", "bzp", "ted", "open-data"],
  "subtitle": "Aggregated open dataset of Polish public procurement notices",
  "description": "Open dataset of Polish public procurement notices (BZP + TED, 2020-2025). See https://github.com/${REPO_OWNER}/${REPO_NAME} for full schema."
}
EOF

    if kaggle datasets status "$KAGGLE_SLUG" &>/dev/null; then
        echo "Updating existing Kaggle dataset..."
        kaggle datasets version -p "$tmpdir" -m "Monthly update ${VERSION}" --dir-mode zip
    else
        echo "Creating new Kaggle dataset..."
        kaggle datasets create -p "$tmpdir" --dir-mode zip --public
    fi
    rm -rf "$tmpdir"
}

publish_zenodo() {
    echo "== Zenodo =="
    : "${ZENODO_TOKEN:?ZENODO_TOKEN not set}"

    # Placeholder — Zenodo REST API flow:
    # 1. POST /api/deposit/depositions → get deposit_id + bucket URL
    # 2. PUT each file to bucket URL
    # 3. PUT metadata (title, creators, description, license = cc-by-4.0)
    # 4. POST /api/deposit/depositions/{id}/actions/publish
    # Full implementation TODO — requires first run manually to pin concept_id
    # for subsequent versions.
    echo "TODO: implement Zenodo REST flow. Placeholder."
    echo "See: https://developers.zenodo.org/#deposit"
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
