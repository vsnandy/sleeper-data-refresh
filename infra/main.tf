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

data "aws_caller_identity" "current" {}

# --- S3 bucket for full player data ---
resource "aws_s3_bucket" "sleeper_data" {
  bucket = var.s3_bucket_name
  force_destroy = true
}


# --- DynamoDB table (multi-league) ---
resource "aws_dynamodb_table" "players" {
  name         = var.dynamo_table_name
  billing_mode   = "PROVISIONED"
  read_capacity = 5
  write_capacity = 10
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

# --- Optional EventBridge rule for weekly refresh ---
resource "aws_cloudwatch_event_rule" "weekly_refresh" {
  name                = "sleeper_data_refresh_weekly"
  schedule_expression = "cron(25 6 ? * TUE *)" # 6:25 AM UTC every Tuesday
}

resource "aws_cloudwatch_event_target" "lambda_target" {
  rule      = aws_cloudwatch_event_rule.weekly_refresh.name
  target_id = "sleeper_refresh_target"
  arn       = aws_lambda_function.controller.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.controller.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.weekly_refresh.arn
}

### --- START: Controller & Chunk‑Processor Additions --- ###

# IAM Role for Controller Lambda
resource "aws_iam_role" "lambda_controller_role" {
  name               = "${var.prefix}-controller-lambda-role"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [{
      Effect    = "Allow",
      Principal = { Service = "lambda.amazonaws.com" },
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_policy" "lambda_controller_policy" {
  name        = "${var.prefix}-controller-lambda-policy"
  description = "Permissions for controller lambda: put S3 object & invoke chunk processor"
  policy      = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Effect   = "Allow",
        Action   = ["s3:PutObject"],
        Resource = "arn:aws:s3:::${var.s3_bucket_name}/players/*"
      },
      {
        Effect   = "Allow",
        Action   = ["lambda:InvokeFunction"],
        Resource = "arn:aws:lambda:${var.region}:${data.aws_caller_identity.current.account_id}:function:${var.prefix}-chunk-processor"
      },
      {
        Effect   = "Allow",
        Action   = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ],
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "controller_attach" {
  role       = aws_iam_role.lambda_controller_role.name
  policy_arn = aws_iam_policy.lambda_controller_policy.arn
}

# IAM Role for Chunk Processor Lambda
resource "aws_iam_role" "lambda_chunk_processor_role" {
  name               = "${var.prefix}-chunk-processor-lambda-role"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [{
      Effect    = "Allow",
      Principal = { Service = "lambda.amazonaws.com" },
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_policy" "lambda_chunk_processor_policy" {
  name        = "${var.prefix}-chunk-processor-lambda-policy"
  description = "Permissions for chunk processor: write to DynamoDB & logs"
  policy      = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Effect   = "Allow",
        Action   = ["dynamodb:BatchWriteItem", "dynamodb:PutItem"],
        Resource = "*"
      },
      {
        Effect   = "Allow",
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "chunk_processor_attach" {
  role       = aws_iam_role.lambda_chunk_processor_role.name
  policy_arn = aws_iam_policy.lambda_chunk_processor_policy.arn
}

# Lambda: Controller
resource "aws_lambda_function" "controller" {
  function_name = "${var.prefix}-controller"
  role          = aws_iam_role.lambda_controller_role.arn
  handler       = "controller_handler.handler"
  runtime       = "python3.12"
  memory_size   = var.controller_memory_size
  timeout       = var.controller_timeout
  filename      = "${path.module}/../build/controller_lambda.zip"

  environment {
    variables = {
      S3_BUCKET         = var.s3_bucket_name
      CHUNK_LAMBDA_NAME = "${var.prefix}-chunk-processor"
      CHUNK_SIZE        = var.chunk_size
    }
  }
}

# Lambda: Chunk Processor
resource "aws_lambda_function" "chunk_processor" {
  function_name = "${var.prefix}-chunk-processor"
  role          = aws_iam_role.lambda_chunk_processor_role.arn
  handler       = "chunk_processor_handler.handler"
  runtime       = "python3.12"
  memory_size   = var.chunk_processor_memory_size
  timeout       = var.chunk_processor_timeout
  filename      = "${path.module}/../build/chunk_processor_lambda.zip"

  environment {
    variables = {
      TABLE_NAME = var.dynamo_table_name
    }
  }
}

# Permission: allow controller to invoke chunk processor
resource "aws_lambda_permission" "controller_invoke_chunk" {
  statement_id  = "AllowControllerToInvokeChunk"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.chunk_processor.function_name
  principal     = "lambda.amazonaws.com"
  source_arn    = aws_lambda_function.controller.arn
}

### --- END: Additions --- ###