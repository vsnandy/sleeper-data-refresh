variable "region" {
  description = "AWS region"
  default     = "us-east-1"
}

variable "s3_bucket_name" {
  description = "Bucket for Sleeper full player JSONs"
  default     = "sleeper-player-data"
}

variable "dynamo_table_name" {
  description = "DynamoDB table for parsed player data"
  default     = "sleeper_players"
}
