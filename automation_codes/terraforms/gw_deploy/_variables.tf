variable "stage" {
  default = "dev"
}
variable "aws_region" {
  default = "ap-south-2"
}
variable "aws_cred_file_loc" {
  default = "/root/.aws/credentials"
}
variable "aws_profile" {
  default = "jakshwealth"
}
variable "gateway_name" {
  default = "jw-api"
}

variable "enable_splunk_logging" {
  type    = bool
  default = false
}

variable "enable_custom_domain" {
  type    = bool
  default = false
}

variable "cigna_tags" {
  description = "Maps of tags required for AWS resource"
  type        = map
  default = {
    CostCenter             = "00079544"
    AssetOwner             = "sridhar.talluri@evernorth.com"
    ServiceNowBA           = "BA12659"
    CiId                   = "CI0009117016"
    ServiceNowAS           = "AS019069"
    SecurityReviewID       = "RITM2908696"
    AsaqId                 = "ASAQ-724791"
    Purpose                = "High Performance Providers - Self Service Analytics"
    Version                = "0.0.1"
    BackupOwner            = "mrinal.patwardhan@evernorth.com"
    DataSubjectArea        = "provider"
    ComplianceDataCategory = "pii:hipaa"
    DataClassification     = "confidential"
    BusinessEntity         = "evernorth"
    LineOfBusiness         = "commercial"
    RegionalRestriction    = "ap-south-2"
    DataOwner              = "gregory.smith2@evernorth.com"
    DataCustodian          = "sridhar.talluri@evernorth.com"
    Inspect                = "N"
    project                = "JakshWealth"
    ResourceName           = "JakshWealth"
    ResourceOwner          = "CM DNA JakshWealth"
    DataRetentionCode      = "7 Years"
  }
}
