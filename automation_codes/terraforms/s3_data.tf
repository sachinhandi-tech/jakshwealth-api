data "aws_s3_bucket_object" "jw_authorization_lambda" {
	bucket = "jakshwealth-artifacts-dev"
	key = "jw-api/jw_authorization.zip"
}
data "aws_s3_bucket_object" "jw_secure_data_lambda" {
	bucket = "jakshwealth-artifacts-dev"
	key = "jw-api/jw_secure_data.zip"
}
data "aws_s3_bucket_object" "jw_app_config_lambda" {
	bucket = "jakshwealth-artifacts-dev"
	key = "jw-api/jw_app_config.zip"
}
data "aws_s3_bucket_object" "jw_authentication_lambda" {
	bucket = "jakshwealth-artifacts-dev"
	key = "jw-api/jw_authentication.zip"
}
