#!/usr/bin/env bash
# Redeploy: run push_images.sh first if you changed code, then run this to
# have the instance pull the new images and restart the stack. Uses SSM
# Session Manager's send-command (no SSH, no open port 22 -- see
# deploy/terraform/security_group.tf) so this needs no key pair.
set -euo pipefail
cd "$(dirname "$0")/../.."

TF_DIR=deploy/terraform
region=$(terraform -chdir="$TF_DIR" output -raw aws_region)
instance_id=$(terraform -chdir="$TF_DIR" output -raw instance_id)

echo "--- sending run.sh via SSM to $instance_id ---"
command_id=$(aws ssm send-command \
  --region "$region" \
  --instance-ids "$instance_id" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["/opt/creditlens/run.sh"]' \
  --comment "creditlens redeploy" \
  --query "Command.CommandId" --output text)

echo "--- waiting for command $command_id to finish ---"
aws ssm wait command-executed --region "$region" --command-id "$command_id" --instance-id "$instance_id" || true

aws ssm get-command-invocation \
  --region "$region" \
  --command-id "$command_id" \
  --instance-id "$instance_id" \
  --query "{Status:Status,StdOut:StandardOutputContent,StdErr:StandardErrorContent}" \
  --output json
