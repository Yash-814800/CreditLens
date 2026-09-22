#!/usr/bin/env bash
# On-demand Postgres backup: pg_dump inside the db container (via SSM, no
# SSH), gzip, upload to the same private/encrypted S3 bucket under backups/
# (a different prefix than seed/ and applications/ -- same bucket, same
# encryption-at-rest and TLS-only policy already enforced by s3.tf).
set -euo pipefail
cd "$(dirname "$0")/../.."

TF_DIR=deploy/terraform
region=$(terraform -chdir="$TF_DIR" output -raw aws_region)
instance_id=$(terraform -chdir="$TF_DIR" output -raw instance_id)
bucket=$(terraform -chdir="$TF_DIR" output -raw s3_bucket_name)
stamp=$(date -u +%Y%m%dT%H%M%SZ)

remote_cmd=$(cat <<CMD
set -e
cd /opt/creditlens
set -a; source .env.prod; set +a
docker compose -f docker-compose.prod.yml exec -T db \
  sh -c 'PGPASSWORD="\$POSTGRES_PASSWORD" pg_dump -U "\$POSTGRES_USER" -d "\$POSTGRES_DB"' | gzip > /tmp/creditlens-$stamp.sql.gz
aws s3 cp /tmp/creditlens-$stamp.sql.gz "s3://$bucket/backups/creditlens-$stamp.sql.gz"
rm -f /tmp/creditlens-$stamp.sql.gz
echo "uploaded s3://$bucket/backups/creditlens-$stamp.sql.gz"
CMD
)

command_id=$(aws ssm send-command \
  --region "$region" \
  --instance-ids "$instance_id" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[$(jq -Rs . <<<"$remote_cmd")]" \
  --comment "creditlens backup" \
  --query "Command.CommandId" --output text)

aws ssm wait command-executed --region "$region" --command-id "$command_id" --instance-id "$instance_id" || true
aws ssm get-command-invocation --region "$region" --command-id "$command_id" --instance-id "$instance_id" \
  --query "{Status:Status,StdOut:StandardOutputContent,StdErr:StandardErrorContent}" --output json
