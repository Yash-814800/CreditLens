output "public_ip" {
  description = "Elastic IP address of the instance."
  value       = aws_eip.app.public_ip
}

output "site_address" {
  description = "HTTPS hostname the app is served at (sslip.io wraps the Elastic IP; no DNS record needed)."
  value       = local.site_address
}

output "s3_bucket_name" {
  description = "Private S3 bucket holding uploaded applicant documents + seed data."
  value       = aws_s3_bucket.docs.bucket
}

output "ecr_backend_repository_url" {
  value = aws_ecr_repository.backend.repository_url
}

output "ecr_frontend_repository_url" {
  value = aws_ecr_repository.frontend.repository_url
}

output "instance_id" {
  description = "Used by deploy/scripts/deploy.sh and backup.sh to target SSM commands."
  value       = aws_instance.app.id
}

output "aws_region" {
  value = var.aws_region
}

output "ssm_session_command" {
  description = "Shell access with no open SSH port -- see security_group.tf."
  value       = "aws ssm start-session --region ${var.aws_region} --target ${aws_instance.app.id}"
}
