variable "aws_region" {
  description = "AWS region. Fixed to Mumbai so applicant data stays in India (see CLAUDE.md)."
  type        = string
  default     = "ap-south-1"
}

variable "project" {
  description = "Short name prefixed onto every resource name/tag."
  type        = string
  default     = "creditlens"
}

variable "environment" {
  description = "Deployment environment tag."
  type        = string
  default     = "prod"
}

variable "instance_type" {
  description = "EC2 instance type. t3.medium (4GB RAM) is the smallest size that comfortably runs db+backend+frontend+caddy together."
  type        = string
  default     = "t3.medium"
}

variable "root_volume_gb" {
  description = "Root EBS volume size in GB. 30GB covers the OS, Docker images, and Postgres data for a demo-scale dataset with headroom."
  type        = number
  default     = 30
}

variable "budget_limit_usd" {
  description = "Hard monthly AWS Budget cap in USD. The user set a $20 total spend ceiling for this project."
  type        = number
  default     = 20
}

variable "budget_warning_pct" {
  description = "Forecasted-spend percentage of budget_limit_usd at which to send an early warning."
  type        = number
  default     = 75
}

variable "budget_alert_email" {
  description = "Email address to receive AWS Budget threshold notifications. No default on purpose -- pass it explicitly (-var or TF_VAR_budget_alert_email) rather than committing a real address."
  type        = string
}

variable "ssm_path_prefix" {
  description = "SSM Parameter Store path prefix under which every app secret/config value lives. The IAM instance policy grants read access scoped to exactly this path."
  type        = string
  default     = "/creditlens/prod"
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention. Kept short to bound storage cost on a $20 budget."
  type        = number
  default     = 14
}
