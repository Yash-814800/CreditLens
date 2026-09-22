data "aws_caller_identity" "current" {}

# Default VPC: deliberately not a custom VPC. A custom VPC with private
# subnets would need a NAT Gateway for the instance to reach the internet
# (Gemini API, ECR, apt, Let's Encrypt) -- a NAT Gateway bills per-hour plus
# per-GB processed even when idle (roughly $1+/day), which alone could blow
# through a $20 total budget in under three weeks. The default VPC's subnets
# are public with an Internet Gateway already attached, so a security group
# is the only access control we need. Documented in docs/deployment.md.
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# One subnet is enough for a single instance with no failover requirement.
data "aws_subnet" "chosen" {
  id = sort(data.aws_subnets.default.ids)[0]
}

# Canonical's official Ubuntu 24.04 LTS (Noble Numbat) AMI, looked up live
# rather than pinned to a hardcoded AMI ID (which would silently go stale
# and eventually be deregistered). Owner 099720109477 is Canonical's
# published AWS account ID.
data "aws_ami" "ubuntu_2404" {
  most_recent = true
  owners      = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }
}

# SSM Parameter Store's SecureString type defaults to the account's AWS-managed
# KMS key (alias/aws/ssm). Using it instead of a customer-managed key avoids
# the ~$1/month KMS key charge -- a deliberate cost/ceremony tradeoff for a
# $20-budget hackathon deployment, documented in docs/deployment.md.
data "aws_kms_alias" "ssm" {
  name = "alias/aws/ssm"
}
