data "aws_api_gateway_rest_api" "rest_api" {
  name = var.gateway_name
}

# Adopt resources renamed from legacy CCD-prefixed Terraform addresses.
moved {
  from = aws_api_gateway_stage.ccdapi_stage
  to   = aws_api_gateway_stage.jw_api_stage
}

moved {
  from = aws_api_gateway_method_settings.ccdapi_method_settings
  to   = aws_api_gateway_method_settings.jw_api_method_settings
}

moved {
  from = aws_api_gateway_base_path_mapping.ccd_base_path
  to   = aws_api_gateway_base_path_mapping.jw_api_base_path
}

resource "aws_api_gateway_deployment" "endpoint_deployment" {
  description = "deployment post endpoint creation: ${md5(file("../api_integration.tf"))}"
  rest_api_id = data.aws_api_gateway_rest_api.rest_api.id

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "jw_api_stage" {
  stage_name    = var.stage
  rest_api_id   = data.aws_api_gateway_rest_api.rest_api.id
  deployment_id = aws_api_gateway_deployment.endpoint_deployment.id
  description   = "Deployed at ${timestamp()}"

  tags = var.project_tags
}

resource "aws_api_gateway_base_path_mapping" "jw_api_base_path" {
  count       = var.enable_custom_domain ? 1 : 0
  depends_on  = [aws_api_gateway_stage.jw_api_stage]
  api_id      = data.aws_api_gateway_rest_api.rest_api.id
  stage_name  = aws_api_gateway_stage.jw_api_stage.stage_name
  domain_name = "${var.gateway_name}-g.jakshwealth-${var.stage}.aws.example.com"
}

resource "aws_api_gateway_method_settings" "jw_api_method_settings" {
  depends_on  = [aws_api_gateway_stage.jw_api_stage]
  rest_api_id = data.aws_api_gateway_rest_api.rest_api.id
  stage_name  = var.stage
  method_path = "*/*"

  settings {
    metrics_enabled = true
    logging_level   = "OFF"
  }
}
