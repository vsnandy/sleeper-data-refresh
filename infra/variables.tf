variable "region" {
  description = "AWS region"
  default     = "us-east-1"
}

variable "s3_bucket_name" {
  description = "Bucket for Sleeper full player JSONs"
  default     = "vsnandy-sleeper-player-data"
}

variable "dynamo_table_name" {
  description = "DynamoDB table for parsed player data"
  default     = "sleeper_players"
}

variable "prefix" {
  description = "Prefix"
  default     = "sleeper"
}

variable "chunk_size" {
  description = "Chunk size"
  default     = 500
}

variable "controller_memory_size" {
  description = "Controller lambda memory size"
  default     = 1024
}

variable "controller_timeout" {
  description = "Controller lambda timeout"
  default     = 60
}

variable "chunk_processor_memory_size" {
  description = "Chunk lambda memory size"
  default     = 1024
}

variable "chunk_processor_timeout" {
  description = "Chunk lambda timeout"
  default     = 60
}