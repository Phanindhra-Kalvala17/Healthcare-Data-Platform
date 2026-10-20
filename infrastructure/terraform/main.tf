terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
  # shortcut: local state file; move to an S3 backend with state locking before a second person applies
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project     = "healthcare-data-platform"
      Environment = var.environment
      DataClass   = "synthetic"
    }
  }
}

variable "region" {
  type = string
}

variable "environment" {
  type = string
}

data "aws_caller_identity" "current" {}

locals {
  name = "hdp-${var.environment}"
}

resource "aws_kms_key" "lake" {
  description             = "${local.name} data lake encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

resource "aws_kms_alias" "lake" {
  name          = "alias/${local.name}-lake"
  target_key_id = aws_kms_key.lake.key_id
}

resource "aws_s3_bucket" "lake" {
  bucket = "${local.name}-lake-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "lake" {
  bucket                  = aws_s3_bucket.lake.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "lake" {
  bucket = aws_s3_bucket.lake.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "lake" {
  bucket = aws_s3_bucket.lake.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.lake.arn
    }
    bucket_key_enabled = true
  }
}

# Policies live as standalone files so IAM Access Analyzer can validate them (scripts/validate_iam_policies.py).
resource "aws_s3_bucket_policy" "lake" {
  bucket = aws_s3_bucket.lake.id
  policy = templatefile("${path.module}/policies/lake-bucket.json.tftpl", { bucket_arn = aws_s3_bucket.lake.arn })
}

resource "aws_iam_role" "pipeline" {
  name               = "${local.name}-pipeline"
  assume_role_policy = templatefile("${path.module}/policies/pipeline-trust.json.tftpl", { account_id = data.aws_caller_identity.current.account_id })
}

resource "aws_iam_role_policy" "pipeline" {
  name = "data-lake-access"
  role = aws_iam_role.pipeline.id
  policy = templatefile("${path.module}/policies/pipeline-data-lake.json.tftpl", {
    bucket_arn  = aws_s3_bucket.lake.arn
    kms_key_arn = aws_kms_key.lake.arn
  })
}

output "lake_bucket" {
  value = aws_s3_bucket.lake.bucket
}

output "pipeline_role_arn" {
  value = aws_iam_role.pipeline.arn
}
