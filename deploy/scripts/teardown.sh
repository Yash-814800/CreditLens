#!/usr/bin/env bash
# Full teardown: destroys every AWS resource this project created (EC2, EIP,
# S3 bucket + all objects, ECR repos + images, IAM role, CloudWatch, Budget).
# For a temporary pause between demo sessions, prefer stopping the instance
# instead -- see docs/cost_and_cleanup.md -- which keeps everything provisioned
# but drops compute cost to ~$0 while stopped. Use THIS script only when you
# are done with the project for good.
set -euo pipefail
cd "$(dirname "$0")/../terraform"

bucket=$(terraform output -raw s3_bucket_name 2>/dev/null || true)
if [ -n "$bucket" ]; then
  echo "--- emptying s3://$bucket (including all object versions -- Terraform cannot destroy a non-empty bucket) ---"
  aws s3api list-object-versions --bucket "$bucket" --output json \
    | jq -c '(.Versions // [] ) + (.DeleteMarkers // [])  | .[] | {Key:.Key,VersionId:.VersionId}' \
    | while read -r obj; do
        key=$(jq -r .Key <<<"$obj"); ver=$(jq -r .VersionId <<<"$obj")
        aws s3api delete-object --bucket "$bucket" --key "$key" --version-id "$ver" >/dev/null
      done
fi

echo ""
echo "About to run: terraform destroy"
echo "This permanently deletes every resource this project created in AWS."
terraform plan -destroy

read -r -p "Type 'destroy' to proceed: " confirm
if [ "$confirm" != "destroy" ]; then
  echo "Aborted -- nothing was destroyed."
  exit 1
fi

terraform destroy -auto-approve
echo "Done. Verify in the AWS Console that nothing billable remains (EC2, EBS, EIP)."
