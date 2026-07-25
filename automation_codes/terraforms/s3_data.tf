data "aws_s3_bucket_object" "jw_secure_data_lambda" {
	bucket = "jakshwealth-artifacts-dev-aps2"
	key = "jw-api/jw_secure_data.zip"
}
data "aws_s3_bucket_object" "jw_app_config_lambda" {
	bucket = "jakshwealth-artifacts-dev-aps2"
	key = "jw-api/jw_app_config.zip"
}
