resource "aws_security_group" "lambda_security_group" {
  count       = var.enable_lambda_vpc ? 1 : 0
  name        = "${var.team_name}_lambda_security_group"
  description = "JakshWealth Lambda egress for HTTPS (Okta, Secrets Manager)"
  vpc_id      = data.aws_vpc.golden[0].id

  ingress = []

  egress = [
    {
      from_port        = 0
      to_port          = 65535
      protocol         = "tcp"
      cidr_blocks      = ["0.0.0.0/0"]
      description      = "Outbound HTTPS and AWS APIs"
      ipv6_cidr_blocks = []
      prefix_list_ids  = []
      security_groups  = []
      self             = false
    }
  ]

  tags = var.cigna_tags
}
