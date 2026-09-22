#!/usr/bin/env bash
# Run from your LOCAL machine (needs your own AWS credentials + Docker), from
# the repo root. Builds the backend/frontend images exactly as `make up`
# does, tags them for ECR, and pushes. Run this before the instance's first
# boot completes (or before deploy.sh) so `docker pull` on the instance has
# something to fetch -- bootstrap.sh's first attempt fails gracefully and
# tells you to do this if you deploy the infra before pushing images.
set -euo pipefail
cd "$(dirname "$0")/../.."

TF_DIR=deploy/terraform
region=$(terraform -chdir="$TF_DIR" output -raw aws_region)
backend_repo=$(terraform -chdir="$TF_DIR" output -raw ecr_backend_repository_url)
frontend_repo=$(terraform -chdir="$TF_DIR" output -raw ecr_frontend_repository_url)
registry="${backend_repo%%/*}"

echo "--- logging in to $registry ---"
aws ecr get-login-password --region "$region" | docker login --username AWS --password-stdin "$registry"

echo "--- building backend ---"
docker build -t "$backend_repo:latest" -f backend/Dockerfile .

echo "--- building frontend ---"
docker build -t "$frontend_repo:latest" ./frontend

echo "--- pushing ---"
docker push "$backend_repo:latest"
docker push "$frontend_repo:latest"

echo "Done. On the instance, run: sudo /opt/creditlens/run.sh"
echo "(or use deploy/scripts/deploy.sh to trigger that remotely over SSM)"
