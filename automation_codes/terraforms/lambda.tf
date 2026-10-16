module "jw_secure_data" {
	source = "../../jakshwealth-infra/deploy/lambda"
	function_name = "jw_secure_data"
	description = "JakshWealth Lambda jw_secure_data"
	s3artifactbucket = "${data.aws_s3_bucket_object.jw_secure_data_lambda.bucket}"
	s3artifactkey = "${data.aws_s3_bucket_object.jw_secure_data_lambda.key}"
	s3objectversion = "${data.aws_s3_bucket_object.jw_secure_data_lambda.version_id}"
	timeout = "900"
	runtime = "python3.12"
memory_size = "512"
	ephemeral_memory = "512"
	alarm_duration = "890000"
	layers = []
	tags = "${var.project_tags}"
	environment = "${var.shortenvironment}"
	environmental_variables = {"ENVIRONMENT": "dev", "LOG_LEVEL": "INFO"}
	subnet_ids = []
	security_group_ids = []
	alert_funnel_arn = ""
	enable_log_subscription = false
	}
module "jw_app_config" {
	source = "../../jakshwealth-infra/deploy/lambda"
	function_name = "jw_app_config"
	description = "JakshWealth Lambda jw_app_config"
	s3artifactbucket = "${data.aws_s3_bucket_object.jw_app_config_lambda.bucket}"
	s3artifactkey = "${data.aws_s3_bucket_object.jw_app_config_lambda.key}"
	s3objectversion = "${data.aws_s3_bucket_object.jw_app_config_lambda.version_id}"
	timeout = "30"
	runtime = "python3.12"
memory_size = "256"
	ephemeral_memory = "512"
	alarm_duration = "890000"
	layers = []
	tags = "${var.project_tags}"
	environment = "${var.shortenvironment}"
	environmental_variables = {"ENVIRONMENT": "dev", "LOG_LEVEL": "INFO"}
	subnet_ids = []
	security_group_ids = []
	alert_funnel_arn = ""
	enable_log_subscription = false
	}
