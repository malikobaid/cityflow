data "aws_acm_certificate" "wildcard" {
  provider    = aws.use1
  domain      = "*.obaidmalik.co.uk"
  types       = ["AMAZON_ISSUED"]
  most_recent = true
}

output "wildcard_cert_arn" {
  value       = data.aws_acm_certificate.wildcard.arn
  description = "Wildcard cert ARN in us-east-1"
}
