# Attach Secrets Manager read policy to JakshWealth Lambda roles.
# Create ``jakshwealth-lambda-secrets`` in your AWS account (or adjust the policy name below).

data "aws_iam_policy" "jw_secrets" {
  name = "jakshwealth-lambda-secrets"
}

resource "aws_iam_role_policy_attachment" "jw_app_config_jw_secrets" {
  role       = "jw_app_config_${var.shortenvironment}"
  policy_arn = data.aws_iam_policy.jw_secrets.arn
  depends_on = [module.jw_app_config]
}

resource "aws_iam_role_policy_attachment" "jw_authentication_jw_secrets" {
  role       = "jw_authentication_${var.shortenvironment}"
  policy_arn = data.aws_iam_policy.jw_secrets.arn
  depends_on = [module.jw_authentication]
}

resource "aws_iam_role_policy_attachment" "jw_authorization_jw_secrets" {
  role       = "jw_authorization_${var.shortenvironment}"
  policy_arn = data.aws_iam_policy.jw_secrets.arn
  depends_on = [module.jw_authorization]
}

resource "aws_iam_role_policy_attachment" "jw_secure_data_jw_secrets" {
  role       = "jw_secure_data_${var.shortenvironment}"
  policy_arn = data.aws_iam_policy.jw_secrets.arn
  depends_on = [module.jw_secure_data]
}
