# Private bucket for uploaded applicant documents (gig-payout screenshots,
# utility bills, bank-statement CSVs). The app only ever reaches this through
# the authenticated API + presigned/streamed reads via S3Storage
# (backend/app/services/ingestion/storage.py) -- there is no public URL path.
resource "aws_s3_bucket" "docs" {
  bucket = local.s3_bucket_name
}

resource "aws_s3_bucket_public_access_block" "docs" {
  bucket = aws_s3_bucket.docs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "docs" {
  bucket = aws_s3_bucket.docs.id
  versioning_configuration {
    status = "Enabled"
  }
}

# SSE-S3 (AES256), not SSE-KMS: a customer-managed KMS key adds ~$1/month plus
# per-request charges for no real security benefit at this threat level (S3
# already encrypts at rest with AES256 either way) -- not worth it against a
# $20 total budget. Documented in docs/deployment.md.
resource "aws_s3_bucket_server_side_encryption_configuration" "docs" {
  bucket = aws_s3_bucket.docs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# Retention: expire noncurrent (superseded/deleted-then-versioned) object
# versions after 30 days so accidental overwrites/deletes are still
# recoverable for a month, but versioning doesn't accumulate storage forever
# on a demo bucket nobody is actively pruning.
resource "aws_s3_bucket_lifecycle_configuration" "docs" {
  bucket = aws_s3_bucket.docs.id

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {} # applies to every object in the bucket

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# Deny any request to this bucket that isn't over TLS -- applicant documents
# are sensitive personal data even though they're synthetic in this demo.
resource "aws_s3_bucket_policy" "docs_deny_insecure_transport" {
  bucket = aws_s3_bucket.docs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.docs.arn,
          "${aws_s3_bucket.docs.arn}/*",
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })
}
