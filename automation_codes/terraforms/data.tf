data "aws_api_gateway_resource" "rest_api_root" {
	rest_api_id = var.rest_api_id
	path        = "/"
}

data "aws_region" "current" {}

