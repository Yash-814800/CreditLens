locals {
  name_prefix    = "${var.project}-${var.environment}"
  s3_bucket_name = "${var.project}-docs-${data.aws_caller_identity.current.account_id}"
  log_group_name = "/${var.project}/${var.environment}/app"
  ssm_arn_prefix = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.ssm_path_prefix}"
}
