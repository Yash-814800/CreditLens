# Allocated standalone (not as part of the instance resource) so its public
# IP is known before the instance's user_data is rendered -- SITE_ADDRESS
# (the sslip.io hostname Caddy requests a cert for) can then be baked into
# the very first boot instead of needing a manual "now edit Caddyfile with
# the IP you were just given" step.
resource "aws_eip" "app" {
  domain = "vpc"
}

locals {
  # e.g. 13.234.56.78 -> 13-234-56-78.sslip.io -- sslip.io resolves any
  # dash-separated IPv4 embedded in the hostname straight back to that IP,
  # so this needs no DNS record of our own.
  site_address = "${replace(aws_eip.app.public_ip, ".", "-")}.sslip.io"
}

resource "aws_instance" "app" {
  ami                    = data.aws_ami.ubuntu_2404.id
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnet.chosen.id
  vpc_security_group_ids = [aws_security_group.web.id]
  iam_instance_profile   = aws_iam_instance_profile.instance.name

  # IMDSv2 required: the older IMDSv1 (plain GET, no session token) is a
  # known SSRF pivot -- a compromised app process could otherwise read the
  # instance's IAM role credentials via an unauthenticated metadata request.
  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gb
    encrypted             = true
    delete_on_termination = true
  }

  user_data = templatefile("${path.module}/../scripts/bootstrap.sh", {
    aws_region       = var.aws_region
    ssm_path_prefix  = var.ssm_path_prefix
    s3_bucket        = local.s3_bucket_name
    log_group_name   = local.log_group_name
    ecr_backend_url  = aws_ecr_repository.backend.repository_url
    ecr_frontend_url = aws_ecr_repository.frontend.repository_url
    site_address     = local.site_address
    compose_b64      = filebase64("${path.module}/../docker-compose.prod.yml")
    caddyfile_b64    = filebase64("${path.module}/../Caddyfile")
  })
  # Editing bootstrap.sh, the compose file, or the Caddyfile should produce a
  # freshly-bootstrapped instance next apply, not a live instance whose
  # user_data silently changed with no effect (EC2 only runs user_data once,
  # on first boot).
  user_data_replace_on_change = true

  tags = {
    Name = "${local.name_prefix}-app"
  }
}

resource "aws_eip_association" "app" {
  instance_id   = aws_instance.app.id
  allocation_id = aws_eip.app.id
}
