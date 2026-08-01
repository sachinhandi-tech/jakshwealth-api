variable "rest_api_id" {
  type        = string
  description = "API Gateway REST API id (pin to avoid ambiguous name lookup)."
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

variable "project_tags" {
  description = "Tags applied to AWS resources"
  type        = map(string)
  default = {
    Project     = "jakshwealth"
    Environment = "dev"
    ManagedBy   = "terraform"
  }
}

variable "shortenvironment" {
  default = "dev"
}

variable "team_name" {
  default = "jw"
}

variable "enable_lambda_vpc" {
  description = "Place Lambdas inside a VPC (requires jakshwealth-vpc from bootstrap)"
  type        = bool
  default     = false
}

variable "splunk_acc_number" {
  description = "Unused for personal deploy"
  default     = ""
}

variable "alert_funnel_arn" {
  description = "SNS topic for CloudWatch alarms; leave empty to skip"
  default     = ""
}
