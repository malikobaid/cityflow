terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

variable "aws_region" {
  description = "Primary AWS region for Phase 0 resources"
  type        = string
  default     = "us-east-1"
}

provider "aws" {
  region  = var.aws_region
  profile = "personal-admin"
}

data "aws_caller_identity" "current" {}

output "account_id" {
  value       = data.aws_caller_identity.current.account_id
  description = "AWS Account ID where resources are created"
}

