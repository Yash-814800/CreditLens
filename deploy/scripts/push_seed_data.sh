#!/usr/bin/env bash
# Run from your LOCAL machine, from the repo root, after `make datagen` has
# produced data/synth/history.parquet and data/demo_pack/. The production
# instance never has a git checkout (see bootstrap.sh), so the two pieces of
# seed data the live app needs -- history.parquet (precedent matching) and
# demo_pack (the demo-persona endpoints) -- are shipped via S3 instead.
set -euo pipefail
cd "$(dirname "$0")/../.."

TF_DIR=deploy/terraform
bucket=$(terraform -chdir="$TF_DIR" output -raw s3_bucket_name)

if [ ! -f data/synth/history.parquet ]; then
  echo "data/synth/history.parquet missing -- run 'make datagen' first." >&2
  exit 1
fi
if [ ! -d data/demo_pack ] || [ -z "$(ls -A data/demo_pack)" ]; then
  echo "data/demo_pack missing/empty -- run 'make datagen' first." >&2
  exit 1
fi

echo "--- uploading history.parquet ---"
aws s3 cp data/synth/history.parquet "s3://$bucket/seed/history.parquet"

echo "--- packaging + uploading demo_pack ---"
tar -czf /tmp/demo_pack.tar.gz -C data demo_pack
aws s3 cp /tmp/demo_pack.tar.gz "s3://$bucket/seed/demo_pack.tar.gz"
rm -f /tmp/demo_pack.tar.gz

echo "Done. On the instance, run.sh will pick these up automatically (only on first run -- delete the on-instance copies under /opt/creditlens/data/ first if you need to force a refresh)."
