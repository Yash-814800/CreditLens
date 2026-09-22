# Parameter Store holds every secret/config value the app needs at runtime.
# Terraform creates the PARAMETERS (so their names/paths/ARNs are reviewable
# and the IAM policy below can be scoped exactly to this path) but never
# their real VALUES -- each is created with an obvious placeholder and then
# `lifecycle.ignore_changes` on value, so Terraform will never overwrite
# whatever real secret gets written afterwards, and a real secret is never
# typed into a .tf file, tfvars, or Terraform state diff shown on screen.
#
# After `terraform apply`, populate the real values from your LOCAL .env
# (never pasted into chat) with, e.g.:
#   aws ssm put-parameter --name "/creditlens/prod/jwt_secret" \
#     --type SecureString --overwrite --value "$(grep '^JWT_SECRET=' .env | cut -d= -f2-)"
# See docs/deployment.md for the full list of put-parameter commands.
#
# The three demo_* passwords are the one exception: bootstrap.sh generates
# them randomly on the instance's first boot (if still at the placeholder)
# and writes them back via put-parameter itself -- see deploy/scripts/bootstrap.sh.
# They are never set by a human and never committed.

locals {
  ssm_secret_names = [
    "postgres_password",
    "app_db_password",
    "database_url",
    "jwt_secret",
    "hmac_pepper",
    "gemini_api_key",
    "gemini_vision_model",
    "gemini_summary_model",
    "demo_underwriter_password",
    "demo_auditor_password",
    "demo_admin_password",
  ]
}

resource "aws_ssm_parameter" "app_secret" {
  for_each = toset(local.ssm_secret_names)

  name        = "${var.ssm_path_prefix}/${each.value}"
  description = "CreditLens ${var.environment} runtime value for ${each.value}. Set for real via the AWS CLI, never via Terraform -- see comment at top of ssm.tf."
  type        = "SecureString"
  value       = "REPLACE_ME_VIA_AWS_CLI_NOT_TERRAFORM"

  lifecycle {
    ignore_changes = [value]
  }
}
