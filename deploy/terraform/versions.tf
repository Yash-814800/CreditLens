terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0, < 6.0"
    }
  }

  # No remote backend configured: this is a single-operator hackathon deployment.
  # State is kept locally (deploy/terraform/terraform.tfstate, gitignored) rather
  # than in S3+DynamoDB, which would add resources purely for team-collaboration
  # locking that a solo deployment doesn't need. Documented in docs/deployment.md.
}
