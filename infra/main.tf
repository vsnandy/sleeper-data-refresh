terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket = "vsnandy-tfstate"
    key    = "sleeper-data-refresh/terraform.tfstate"
    region = "us-east-1"
  }

  required_version = ">= 1.5.0"
}

provider "aws" {
  region = var.region
}

# --- S3 bucket for full player data ---
resource "aws_s3_bucket" "sleeper_data" {
  bucket = var.s3_bucket_name
  force_destroy = true
}


# --- DynamoDB table (multi-league) ---
resource "aws_dynamodb_table" "players" {
  name         = var.dynamo_table_name
  billing_mode   = "PROVISIONED"
  read_capacity = 1
  write_capacity = 1
  hash_key     = "league"
  range_key    = "player_id"

  attribute {
    name = "league"
    type = "S"
  }

  attribute {
    name = "player_id"
    type = "S"
  }
}


# --- IAM role for Lambda ---
resource "aws_iam_role" "lambda_role" {
  name = "sleeper_data_lambda_role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect = "Allow",
      Principal = { Service = "lambda.amazonaws.com" },
      Action = "sts:AssumeRole"
    }]
  })
}

# Attach inline policy for DynamoDB + S3
resource "aws_iam_role_policy" "lambda_policy" {
  name = "sleeper_data_lambda_policy"
  role = aws_iam_role.lambda_role.id
  policy = file("${path.module}/policies/lambda_policy.json")
}

# --- Lambda function ---
resource "aws_lambda_function" "sleeper_data_refresh" {
  function_name = "sleeper_data_refresh"
  handler       = "handler.handler"
  runtime       = "python3.12"

  timeout       = 60

  role          = aws_iam_role.lambda_role.arn
  filename      = "${path.module}/../build/lambda.zip"

  environment {
    variables = {
      S3_BUCKET  = aws_s3_bucket.sleeper_data.bucket
      TABLE_NAME = aws_dynamodb_table.players.name
    }
  }
}

# --- Optional EventBridge rule for weekly refresh ---
resource "aws_cloudwatch_event_rule" "weekly_refresh" {
  name                = "sleeper_data_refresh_weekly"
  schedule_expression = "cron(30 5 ? * TUE *)" # 5 AM UTC every Tuesday
}

resource "aws_cloudwatch_event_target" "lambda_target" {
  rule      = aws_cloudwatch_event_rule.weekly_refresh.name
  target_id = "sleeper_refresh_target"
  arn       = aws_lambda_function.sleeper_data_refresh.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.sleeper_data_refresh.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.weekly_refresh.arn
}
