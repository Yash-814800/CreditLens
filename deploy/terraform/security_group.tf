# No port 22 rule at all, by design (per the phase spec's "better: no SSH,
# use SSM Session Manager" option) -- the IAM role's AmazonSSMManagedInstanceCore
# attachment gives shell access via `aws ssm start-session`, which needs no
# open inbound port, no key pair to manage or leak, and is fully audited in
# CloudTrail. See docs/deployment.md for the exact session command.
resource "aws_security_group" "web" {
  name        = "${local.name_prefix}-web"
  description = "CreditLens ${var.environment}: public HTTP(S) only, no SSH"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP (redirects to HTTPS via Caddy)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "All outbound (Gemini API, ECR/apt package pulls, Lets Encrypt, SSM)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
