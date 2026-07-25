data "aws_api_gateway_rest_api" "rest_api" {
  name = var.gateway_name
}

resource "aws_cloudwatch_log_group" "CCD_APIG_Logs" {
  name = "API-Gateway-Execution-Logs_${data.aws_api_gateway_rest_api.rest_api.id}/${var.stage}"
  tags = var.cigna_tags
}

resource "aws_cloudwatch_log_subscription_filter" "splunkAPIG" {
  count           = var.enable_splunk_logging ? 1 : 0
  depends_on      = [aws_cloudwatch_log_group.CCD_APIG_Logs]
  name            = "CCD_APIG_Logs"
  log_group_name  = "API-Gateway-Execution-Logs_${data.aws_api_gateway_rest_api.rest_api.id}/${var.stage}"
  filter_pattern  = ""
  destination_arn = "arn:aws:logs:${var.aws_region}:746770431074:destination:CentralizedLogging-v2-Destination"
  distribution    = "ByLogStream"
}

resource "aws_api_gateway_stage" "ccdapi_stage" {
  depends_on    = [aws_cloudwatch_log_group.CCD_APIG_Logs]
  stage_name    = var.stage
  rest_api_id   = data.aws_api_gateway_rest_api.rest_api.id
  deployment_id = aws_api_gateway_deployment.endpoint_deployment.id
  description   = "Deployed at ${timestamp()}"

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.CCD_APIG_Logs.arn
    format          = "$context.identity.sourceIp,$context.identity.caller,$context.identity.user,$context.requestTime,$context.httpMethod,$context.resourcePath,$context.protocol,$context.status,$context.responseLength,$context.requestId"
  }
  cache_cluster_size = "0.5"

  tags = var.cigna_tags
}

resource "aws_api_gateway_deployment" "endpoint_deployment" {
  description = "deployment post endpoint creation: ${md5(file("../api_integration.tf"))}"
  rest_api_id = data.aws_api_gateway_rest_api.rest_api.id

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_base_path_mapping" "ccd_base_path" {
  count       = var.enable_custom_domain ? 1 : 0
  depends_on  = [aws_api_gateway_stage.ccdapi_stage]
  api_id      = data.aws_api_gateway_rest_api.rest_api.id
  stage_name  = aws_api_gateway_stage.ccdapi_stage.stage_name
  domain_name = "${var.gateway_name}-g.jakshwealth-${var.stage}.aws.example.com"
}

resource "aws_api_gateway_method_settings" "ccdapi_method_settings" {
  depends_on   = [aws_api_gateway_stage.ccdapi_stage]
  rest_api_id  = data.aws_api_gateway_rest_api.rest_api.id
  stage_name   = var.stage
  method_path  = "*/*"

  settings {
    metrics_enabled = true
    logging_level   = "INFO"
  }
}
