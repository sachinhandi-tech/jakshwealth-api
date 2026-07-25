data "aws_caller_identity" "current" { }

module "jw_api_resource" { 
	source = "../../jakshwealth-infra/deploy/api-gateway-resource"
	rest_api_id = "${data.aws_api_gateway_rest_api.rest_api.id}"
	root_resource_id = "${data.aws_api_gateway_rest_api.rest_api.root_resource_id}"
	path = "jw-api"
}
module "jw_api_secure_data_resource" { 
	source = "../../jakshwealth-infra/deploy/api-gateway-resource"
	rest_api_id = "${data.aws_api_gateway_rest_api.rest_api.id}"
	root_resource_id = "${module.jw_api_resource.resource_id}"
	path = "secure-data"
}
module "jw_api_secure_data_lambda_permission" {
	source = "../../jakshwealth-infra/deploy/api-lambda-permission"
	rest_api_id = "${data.aws_api_gateway_rest_api.rest_api.id}"
	lambda = "${module.jw_secure_data.name}"
	region = "${var.aws_region}"
	account_id  = "${data.aws_caller_identity.current.account_id}"
}
module "get_jw_api_secure_data" {
	source = "../../jakshwealth-infra/deploy/api-gateway-integration-jw"
	rest_api_id = "${data.aws_api_gateway_rest_api.rest_api.id}"
	resource_id = "${module.jw_api_secure_data_resource.resource_id}"
	method = "GET"
	path = "${module.jw_api_secure_data_resource.path}"
	lambda = "${module.jw_secure_data.name}"
	region = "${var.aws_region}"
	account_id = "${data.aws_caller_identity.current.account_id}"
	authorization = "false"
	stage = "dev"
	
}
module "post_jw_api_secure_data" {
	source = "../../jakshwealth-infra/deploy/api-gateway-integration-jw"
	rest_api_id = "${data.aws_api_gateway_rest_api.rest_api.id}"
	resource_id = "${module.jw_api_secure_data_resource.resource_id}"
	method = "POST"
	path = "${module.jw_api_secure_data_resource.path}"
	lambda = "${module.jw_secure_data.name}"
	region = "${var.aws_region}"
	account_id = "${data.aws_caller_identity.current.account_id}"
	authorization = "false"
	stage = "dev"
	
}
module "options_jw_api_secure_data" {
	source = "../../jakshwealth-infra/deploy/api-gateway-integration-jw"
	rest_api_id = "${data.aws_api_gateway_rest_api.rest_api.id}"
	resource_id = "${module.jw_api_secure_data_resource.resource_id}"
	method = "OPTIONS"
	path = "${module.jw_api_secure_data_resource.path}"
	lambda = "${module.jw_secure_data.name}"
	region = "${var.aws_region}"
	account_id = "${data.aws_caller_identity.current.account_id}"
	authorization = "false"
	stage = "dev"
	
}
module "jw_api_secure_data_proxy_resource" { 
	source = "../../jakshwealth-infra/deploy/api-gateway-resource"
	rest_api_id = "${data.aws_api_gateway_rest_api.rest_api.id}"
	root_resource_id = "${module.jw_api_secure_data_resource.resource_id}"
	path = "{proxy+}"
}
module "get_jw_api_secure_data_proxy" {
	source = "../../jakshwealth-infra/deploy/api-gateway-integration-jw"
	rest_api_id = "${data.aws_api_gateway_rest_api.rest_api.id}"
	resource_id = "${module.jw_api_secure_data_proxy_resource.resource_id}"
	method = "GET"
	path = "${module.jw_api_secure_data_proxy_resource.path}"
	lambda = "${module.jw_secure_data.name}"
	region = "${var.aws_region}"
	account_id = "${data.aws_caller_identity.current.account_id}"
	authorization = "false"
	stage = "dev"
	
}
module "post_jw_api_secure_data_proxy" {
	source = "../../jakshwealth-infra/deploy/api-gateway-integration-jw"
	rest_api_id = "${data.aws_api_gateway_rest_api.rest_api.id}"
	resource_id = "${module.jw_api_secure_data_proxy_resource.resource_id}"
	method = "POST"
	path = "${module.jw_api_secure_data_proxy_resource.path}"
	lambda = "${module.jw_secure_data.name}"
	region = "${var.aws_region}"
	account_id = "${data.aws_caller_identity.current.account_id}"
	authorization = "false"
	stage = "dev"
	
}
module "options_jw_api_secure_data_proxy" {
	source = "../../jakshwealth-infra/deploy/api-gateway-integration-jw"
	rest_api_id = "${data.aws_api_gateway_rest_api.rest_api.id}"
	resource_id = "${module.jw_api_secure_data_proxy_resource.resource_id}"
	method = "OPTIONS"
	path = "${module.jw_api_secure_data_proxy_resource.path}"
	lambda = "${module.jw_secure_data.name}"
	region = "${var.aws_region}"
	account_id = "${data.aws_caller_identity.current.account_id}"
	authorization = "false"
	stage = "dev"
	
}
module "jw_api_app_config_resource" { 
	source = "../../jakshwealth-infra/deploy/api-gateway-resource"
	rest_api_id = "${data.aws_api_gateway_rest_api.rest_api.id}"
	root_resource_id = "${module.jw_api_resource.resource_id}"
	path = "app-config"
}
module "jw_api_app_config_lambda_permission" {
	source = "../../jakshwealth-infra/deploy/api-lambda-permission"
	rest_api_id = "${data.aws_api_gateway_rest_api.rest_api.id}"
	lambda = "${module.jw_app_config.name}"
	region = "${var.aws_region}"
	account_id  = "${data.aws_caller_identity.current.account_id}"
}
module "get_jw_api_app_config" {
	source = "../../jakshwealth-infra/deploy/api-gateway-integration-jw"
	rest_api_id = "${data.aws_api_gateway_rest_api.rest_api.id}"
	resource_id = "${module.jw_api_app_config_resource.resource_id}"
	method = "GET"
	path = "${module.jw_api_app_config_resource.path}"
	lambda = "${module.jw_app_config.name}"
	region = "${var.aws_region}"
	account_id = "${data.aws_caller_identity.current.account_id}"
	authorization = "false"
	stage = "dev"
	
}
module "options_jw_api_app_config" {
	source = "../../jakshwealth-infra/deploy/api-gateway-integration-jw"
	rest_api_id = "${data.aws_api_gateway_rest_api.rest_api.id}"
	resource_id = "${module.jw_api_app_config_resource.resource_id}"
	method = "OPTIONS"
	path = "${module.jw_api_app_config_resource.path}"
	lambda = "${module.jw_app_config.name}"
	region = "${var.aws_region}"
	account_id = "${data.aws_caller_identity.current.account_id}"
	authorization = "false"
	stage = "dev"
	
}