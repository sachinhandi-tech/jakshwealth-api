data "aws_api_gateway_rest_api" "rest_api" {
	name = "jw-api"
}

data "aws_region" "current" {}

