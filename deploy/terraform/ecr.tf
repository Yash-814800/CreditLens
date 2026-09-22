# Private image registries. Preferred deployment path (see docs/deployment.md):
# build images locally, push to these repos, the instance pulls via its IAM
# role -- no long-lived credentials or a private git token ever touch the
# instance. Falls back to a git-clone-on-instance approach if ECR push isn't
# available (documented, not implemented, since it needs a real push to test).
resource "aws_ecr_repository" "backend" {
  name                 = "${var.project}/backend"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "frontend" {
  name                 = "${var.project}/frontend"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Expire untagged images after a week so a build-and-push habit doesn't
# quietly accumulate storage cost -- ECR storage is billed per GB-month.
resource "aws_ecr_lifecycle_policy" "expire_untagged" {
  for_each   = { backend = aws_ecr_repository.backend.name, frontend = aws_ecr_repository.frontend.name }
  repository = each.value

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      }
    ]
  })
}
