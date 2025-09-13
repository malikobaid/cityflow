# Allow the CityFlowCICD role to deploy the static site (S3) and invalidate CloudFront

# Replace if you named the role differently
locals {
  cicd_role_name = "CityFlowCICD"
}

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "cicd_phase1" {
  statement {
    sid     = "ListAndLocateBucket"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation"
    ]
    resources = [
      "arn:aws:s3:::${aws_s3_bucket.web.bucket}"
    ]
  }

  statement {
    sid     = "WriteSiteObjects"
    actions = [
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:PutObjectTagging",
      "s3:DeleteObjectTagging"
    ]
    resources = [
      "arn:aws:s3:::${aws_s3_bucket.web.bucket}/*"
    ]
  }

  # CloudFront invalidation. Some orgs prefer resource-level; "*" also works.
  statement {
    sid     = "CreateInvalidation"
    actions = ["cloudfront:CreateInvalidation"]
    resources = [
      "arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/${aws_cloudfront_distribution.web.id}"
    ]
  }
}

resource "aws_iam_role_policy" "cicd_phase1" {
  name   = "CityFlowCICD-Phase1"
  role   = local.cicd_role_name
  policy = data.aws_iam_policy_document.cicd_phase1.json
}
