locals {
  # GitHub repo allowed to assume this role
  repo = "malikobaid/cityflow"
}

resource "aws_iam_role" "cityflow_cicd" {
  name = "CityFlowCICD"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = "sts:AssumeRoleWithWebIdentity",
        Principal = {
          Federated = aws_iam_openid_connect_provider.github.arn
        },
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          },
          StringLike = {
            "token.actions.githubusercontent.com:sub" = [
              "repo:${local.repo}:ref:refs/heads/main",
              "repo:${local.repo}:ref:refs/tags/*",
              "repo:${local.repo}:pull_request",
            ]
          }
        }
      }
    ]
  })
}

output "cicd_role_arn" {
  description = "IAM role ARN to be assumed by GitHub Actions via OIDC"
  value       = aws_iam_role.cityflow_cicd.arn
}

