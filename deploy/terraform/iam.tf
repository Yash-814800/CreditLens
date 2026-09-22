data "aws_iam_policy_document" "ec2_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "instance" {
  name               = "${local.name_prefix}-ec2-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_trust.json
}

resource "aws_iam_instance_profile" "instance" {
  name = "${local.name_prefix}-ec2-profile"
  role = aws_iam_role.instance.name
}

# AWS-managed policy: grants exactly what SSM Session Manager needs to give
# us a shell on the instance with port 22 closed entirely (see security_group.tf).
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Least-privilege application access: no wildcard resource ARNs except the
# two actions AWS itself does not support resource-level restriction on
# (ecr:GetAuthorizationToken, logs:DescribeLogGroups) -- both are read-only
# and account-scoped by IAM's own trust boundary regardless of the "*".
data "aws_iam_policy_document" "app_access" {
  statement {
    sid     = "ReadOwnSsmParameters"
    effect  = "Allow"
    actions = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
    # GetParametersByPath authorizes against the exact path ARN passed to
    # --path (no trailing "/*"), while GetParameter/GetParameters need the
    # "/*" form for the individual parameter names under it -- both forms
    # are required or the recursive fetch in bootstrap.sh's run.sh is denied.
    resources = [local.ssm_arn_prefix, "${local.ssm_arn_prefix}/*"]
  }

  # Scoped narrower than the read above: only bootstrap.sh's one-time
  # demo-password generation writes back to SSM, and only to those three
  # specific parameters -- it can never overwrite JWT_SECRET, DB passwords, etc.
  statement {
    sid     = "WriteGeneratedDemoPasswordsOnly"
    effect  = "Allow"
    actions = ["ssm:PutParameter"]
    resources = [
      "${local.ssm_arn_prefix}/demo_underwriter_password",
      "${local.ssm_arn_prefix}/demo_auditor_password",
      "${local.ssm_arn_prefix}/demo_admin_password",
    ]
  }

  statement {
    sid       = "DecryptSsmSecureStrings"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]
    resources = [data.aws_kms_alias.ssm.target_key_arn]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.aws_region}.amazonaws.com"]
    }
  }

  statement {
    sid       = "DocumentBucketReadWrite"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.docs.arn}/*"]
  }

  statement {
    sid       = "DocumentBucketList"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.docs.arn]
  }

  statement {
    sid       = "WriteAppLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.app.arn}:*"]
  }

  statement {
    sid       = "DescribeLogGroupForAgentSetup"
    effect    = "Allow"
    actions   = ["logs:DescribeLogGroups", "logs:DescribeLogStreams"]
    resources = ["*"]
  }

  statement {
    sid       = "PullOwnEcrImages"
    effect    = "Allow"
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"]
    resources = [aws_ecr_repository.backend.arn, aws_ecr_repository.frontend.arn]
  }

  # ECR auth tokens are account/region-wide by design -- the API does not
  # accept a repository-scoped resource here, so "*" is the only valid value.
  statement {
    sid       = "EcrAuthToken"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "app_access" {
  name   = "${local.name_prefix}-app-access"
  role   = aws_iam_role.instance.id
  policy = data.aws_iam_policy_document.app_access.json
}
