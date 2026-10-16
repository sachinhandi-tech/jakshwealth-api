variable "rest_api_id" {
  type        = string
  description = "API Gateway REST API id (pin to avoid ambiguous name lookup)."
}

variable "stage" {
  default = "dev"
}

variable "aws_region" {
  default = "ap-south-2"
}

variable "aws_cred_file_loc" {
  default = "/root/.aws/credentials"
}

variable "aws_profile" {
  default = "jakshwealth"
}

variable "gateway_name" {
  default = "jw-api"
}

variable "enable_custom_domain" {
  type    = bool
  default = false
}

variable "project_tags" {
  description = "Tags applied to AWS resources"
  type        = map(string)
  default = {
    Project     = "jakshwealth"
    Environment = "dev"
    ManagedBy   = "terraform"
  }
}
