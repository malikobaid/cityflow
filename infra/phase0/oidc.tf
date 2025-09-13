# GitHub Actions OIDC provider for AWS STS
# If you already have this provider in your account, you can import it:
#   terraform import aws_iam_openid_connect_provider.github <existing-oidc-arn>

resource "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"

  client_id_list = [
    "sts.amazonaws.com",
  ]

  # Thumbprint for GitHub's OIDC provider (DigiCert Global Root G2)
  # Ref: https://docs.github.com/actions/deployment/security-hardening-your-deployments/about-security-hardening-with-openid-connect
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1"
  ]
}

