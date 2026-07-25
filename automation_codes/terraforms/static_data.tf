data "aws_vpc" "golden" {
  filter {
    name   = "tag:Name"
    values = ["jakshwealth-vpc"]
  }
}

data "aws_subnets" "golden-subnets" {
  filter {
    name   = "tag:Name"
    values = ["jakshwealth-subnet-001"]
  }
}

data "aws_subnets" "pod-subnets" {
  filter {
    name   = "tag:Name"
    values = ["jakshwealth-pod-subnet*"]
  }
}
