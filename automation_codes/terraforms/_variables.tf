variable "aws_region" {
  default = "us-east-1"
}
variable "aws_cred_file_loc" {
  default = "/root/.aws/credentials"
}
variable "aws_profile" {
  default = "jakshwealth"
}

variable "cigna_tags" {
  description = "Maps of tags required for AWS resource"
  type        = map
  default = {
    CostCenter             = "00079544"
    AssetOwner             = "CHARAN.SINGH@evernorth.com"
    ServiceNowBA           = "BA12659"
    CiId                   = "CI0009117016"
    ServiceNowAS           = "AS019069"
    SecurityReviewID       = "ASAQ-1484748"
    AsaqId                 = "ASAQ-724791"
    Purpose                = "High Performance Providers - Self Service Analytics"
    Version                = "0.0.1"
    BackupOwner            = "mrinal.patwardhan@evernorth.com"
    DataSubjectArea        = "provider"
    ComplianceDataCategory = "pii:hipaa"
    DataClassification     = "confidential"
    BusinessEntity         = "evernorth"
    LineOfBusiness         = "commercial"
    RegionalRestriction    = "us-east-1"
    DataOwner              = "gregory.smith2@evernorth.com"
    DataCustodian          = "sridhar.talluri@evernorth.com"
    Inspect                = "N"
    project                = "JakshWealth"
    ResourceName           = "JakshWealth"
    ResourceOwner          = "CM DNA JakshWealth"
    DataRetentionCode      = "7 Years"
  }
}

variable "shortenvironment" {
  default = "dev"
}

variable "team_name" {
  default = "ssa"
}

variable "splunk_acc_number" {
  description = "centralised splunk account number"
  default     = "746770431074"
}

variable "alert_funnel_arn" {
  description = "centralized funnel arn"
}
