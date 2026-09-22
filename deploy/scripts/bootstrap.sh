#!/usr/bin/env bash
# EC2 user-data: ONE-TIME instance setup, rendered from this file by
# Terraform's templatefile() (see deploy/terraform/ec2.tf) with the values
# below substituted in. Everything here is idempotent-safe to re-run (cloud-init
# only runs user-data once per instance on first boot, but re-running this
# script by hand over SSM Session Manager should never corrupt anything).
#
# NOTE ON $ SYNTAX: this file is a Terraform template. A bare $$VAR or $$(...)
# is left alone by templatefile(), but bash's $${VAR} brace syntax collides
# with Terraform's own $${...} interpolation -- every REAL bash brace
# expansion below is deliberately written with a doubled leading $ so
# Terraform emits a literal single-$ brace form for bash to interpret.
# Anything below written with a single leading $ before a brace is a genuine
# Terraform template variable, not a bash one.
set -euo pipefail
exec > >(tee -a /var/log/creditlens-bootstrap.log) 2>&1
echo "=== CreditLens bootstrap starting: $(date -u +%FT%TZ) ==="

AWS_REGION="${aws_region}"
SSM_PATH_PREFIX="${ssm_path_prefix}"
S3_BUCKET="${s3_bucket}"
LOG_GROUP="${log_group_name}"
ECR_BACKEND_URL="${ecr_backend_url}"
ECR_FRONTEND_URL="${ecr_frontend_url}"
SITE_ADDRESS="${site_address}"
APP_DIR=/opt/creditlens

mkdir -p "$APP_DIR" "$APP_DIR/data"
# 711 (not 700): the backend container's bind-mounted /opt/creditlens/data
# needs to be traversable by the container's non-root uid-1000 "app" user
# (see backend/Dockerfile's comment on that UID), which requires execute
# permission on every ancestor directory including this one -- 700 blocked
# that entirely (PermissionError on the very first real deploy), even
# though .env.prod inside this directory has its own separate 600 below and
# stays unreadable by anyone but root either way. --x--x for group/other
# still prevents `ls`-ing this directory's contents.
chmod 711 "$APP_DIR"

# --- 1. Docker Engine + Compose plugin -------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  echo "--- installing Docker ---"
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
fi

# unzip/jq/openssl are needed by the AWS CLI install and later steps below --
# installed up front so the AWS CLI step never fails on a minimal Ubuntu image.
apt-get update -y && apt-get install -y --no-install-recommends unzip jq openssl >/dev/null

# --- 2. AWS CLI v2 (Ubuntu's apt package is the deprecated v1) -------------
if ! command -v aws >/dev/null 2>&1; then
  echo "--- installing AWS CLI v2 ---"
  tmp_dir=$(mktemp -d)
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-$(uname -m).zip" -o "$tmp_dir/awscliv2.zip"
  unzip -q "$tmp_dir/awscliv2.zip" -d "$tmp_dir"
  "$tmp_dir/aws/install"
  rm -rf "$tmp_dir"
fi

# --- 3. Write the (reviewable, git-tracked) compose file + Caddyfile -------
# Delivered as base64 rather than raw heredocs so nothing in either file's
# own syntax (docker-compose's own $${VAR} interpolation, Caddy's {$VAR})
# has to be escaped for or fought with Terraform's templatefile().
echo "${compose_b64}" | base64 -d > "$APP_DIR/docker-compose.prod.yml"
echo "${caddyfile_b64}" | base64 -d > "$APP_DIR/Caddyfile"

# --- 4. Fetch secrets from SSM, write the root-only runtime env file -------
echo "--- fetching secrets from SSM ($SSM_PATH_PREFIX) ---"
params_json=$(aws ssm get-parameters-by-path \
  --region "$AWS_REGION" \
  --path "$SSM_PATH_PREFIX" \
  --with-decryption \
  --recursive \
  --output json)

env_file="$APP_DIR/.env.prod"
umask 077
: > "$env_file"

# Non-secret config: known at deploy time, no SSM round-trip needed.
{
  echo "APP_ENV=production"
  echo "LOG_LEVEL=INFO"
  echo "POSTGRES_DB=creditlens"
  echo "POSTGRES_USER=creditlens_admin"
  echo "APP_DB_USER=creditlens_app"
  echo "JWT_EXPIRE_MINUTES=30"
  echo "MOCK_LLM=false"
  echo "GEMINI_MAX_CALLS_PER_RUN=20"
  echo "STORAGE_BACKEND=s3"
  echo "S3_BUCKET=$S3_BUCKET"
  echo "AWS_REGION=$AWS_REGION"
  echo "CORS_ORIGINS=https://$SITE_ADDRESS"
  echo "MAX_UPLOAD_MB=15"
  echo "RATE_LIMIT_LOGIN=5/minute"
  echo "RATE_LIMIT_UPLOAD=10/minute"
  echo "ENABLE_DEMO_ENDPOINTS=true"
  echo "SITE_ADDRESS=$SITE_ADDRESS"
  echo "ECR_BACKEND_IMAGE=$ECR_BACKEND_URL:latest"
  echo "ECR_FRONTEND_IMAGE=$ECR_FRONTEND_URL:latest"
  echo "AWS_LOG_GROUP=$LOG_GROUP"
} >> "$env_file"

# Secrets: one SSM parameter -> one UPPER_SNAKE_CASE env var, name derived
# from the parameter's own path suffix (e.g. .../jwt_secret -> JWT_SECRET).
jq -r '.Parameters[] | "\(.Name)\t\(.Value)"' <<<"$params_json" | while IFS=$'\t' read -r name value; do
  suffix=$(basename "$name")
  key=$(echo "$suffix" | tr '[:lower:]' '[:upper:]')
  printf '%s=%s\n' "$key" "$value" >> "$env_file"
done
chmod 600 "$env_file"

placeholder="REPLACE_ME_VIA_AWS_CLI_NOT_TERRAFORM"
if grep -q "^JWT_SECRET=$placeholder$" "$env_file" || grep -q "^GEMINI_API_KEY=$placeholder$" "$env_file"; then
  echo "!!! WARNING: one or more real secrets have not been set in SSM yet."
  echo "!!! The app will refuse to start in production mode until you run the"
  echo "!!! 'aws ssm put-parameter --overwrite ...' commands in docs/deployment.md,"
  echo "!!! then re-run: sudo /opt/creditlens/run.sh"
fi

# --- 5. Generate demo-user passwords on first boot only --------------------
# Never set by a human, never committed -- generated once, written back to
# SSM so `docs/deployment.md`'s "show once" step (aws ssm get-parameter) can
# retrieve them, and so a later re-run of this script doesn't regenerate them.
for demo_param in demo_underwriter_password demo_auditor_password demo_admin_password; do
  current=$(jq -r --arg n "$SSM_PATH_PREFIX/$demo_param" '.Parameters[] | select(.Name==$n) | .Value' <<<"$params_json")
  if [ "$current" = "$placeholder" ] || [ -z "$current" ]; then
    new_pw=$(openssl rand -base64 18 | tr -d '=+/' | cut -c1-24)
    aws ssm put-parameter --region "$AWS_REGION" --overwrite --type SecureString \
      --name "$SSM_PATH_PREFIX/$demo_param" --value "$new_pw" >/dev/null
    key=$(echo "$demo_param" | tr '[:lower:]' '[:upper:]')
    sed -i "s|^$key=.*|$key=$new_pw|" "$env_file"
    echo "Generated $demo_param (view later with: aws ssm get-parameter --with-decryption --name $SSM_PATH_PREFIX/$demo_param)"
  fi
done

# --- 6. Write the idempotent "bring the stack up" script and run it --------
cat > "$APP_DIR/run.sh" <<'RUN_EOF'
#!/usr/bin/env bash
set -euo pipefail
cd /opt/creditlens
set -a; source .env.prod; set +a

echo "--- ECR login ---"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$(echo "$ECR_BACKEND_IMAGE" | cut -d/ -f1)"

echo "--- pulling images ---"
if ! docker pull "$ECR_BACKEND_IMAGE" || ! docker pull "$ECR_FRONTEND_IMAGE"; then
  echo "!!! Image pull failed -- have you pushed images yet?"
  echo "!!! Run deploy/scripts/push_images.sh from your local machine first, then re-run this script."
  exit 1
fi

echo "--- fetching seed data from S3 (skipped if already present) ---"
mkdir -p data/synth data/demo_pack
if [ ! -f data/synth/history.parquet ]; then
  aws s3 cp "s3://$S3_BUCKET/seed/history.parquet" data/synth/history.parquet
fi
if [ ! "$(ls -A data/demo_pack 2>/dev/null)" ]; then
  aws s3 cp "s3://$S3_BUCKET/seed/demo_pack.tar.gz" /tmp/demo_pack.tar.gz
  tar -xzf /tmp/demo_pack.tar.gz -C data/demo_pack --strip-components=1
  rm -f /tmp/demo_pack.tar.gz
fi

# run.sh runs as root (via SSM RunShellScript / cloud-init), so the S3
# downloads above land owned by root -- the backend container runs as
# uid/gid 1000 (see backend/Dockerfile), so without this it can read
# nothing under the bind-mounted data/ dir, and can't write its extraction
# cache there either.
chown -R 1000:1000 data

echo "--- docker compose up ---"
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d

echo "--- waiting for backend health ---"
for i in $(seq 1 60); do
  status=$(docker compose -f docker-compose.prod.yml ps --format '{{.Health}}' backend 2>/dev/null || true)
  [ "$status" = "healthy" ] && break
  [ "$i" = "60" ] && { echo "backend never became healthy -- check: docker compose -f docker-compose.prod.yml logs backend"; exit 1; }
  sleep 3
done

echo "--- running migrations ---"
docker compose -f docker-compose.prod.yml exec -T backend alembic upgrade head

echo "--- seeding demo users (idempotent) ---"
docker compose -f docker-compose.prod.yml exec -T backend python -m app.scripts.seed

echo "--- seeding history (idempotent) ---"
docker compose -f docker-compose.prod.yml exec -T backend python scripts/seed_history.py

echo "=== run.sh complete: $(date -u +%FT%TZ) ==="
RUN_EOF
chmod 700 "$APP_DIR/run.sh"

echo "--- attempting first bring-up (non-fatal if images aren't pushed yet) ---"
"$APP_DIR/run.sh" || echo ">>> First bring-up did not complete -- see message above. Push images then re-run: sudo $APP_DIR/run.sh"

echo "=== CreditLens bootstrap finished: $(date -u +%FT%TZ) ==="
