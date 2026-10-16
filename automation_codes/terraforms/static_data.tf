data "aws_vpc" "golden" {
  count = var.enable_lambda_vpc ? 1 : 0
  filter {
    name   = "tag:Name"
    values = ["jakshwealth-vpc"]
  }
}

data "aws_subnets" "golden-subnets" {
  count = var.enable_lambda_vpc ? 1 : 0
  filter {
    name   = "tag:Name"
    values = ["jakshwealth-subnet-001"]
  }
}

data "aws_subnets" "pod-subnets" {
  count = var.enable_lambda_vpc ? 1 : 0
  filter {
    name   = "tag:Name"
    values = ["jakshwealth-pod-subnet*"]
  }
}
