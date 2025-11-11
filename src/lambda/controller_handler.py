# file: controller_handler.py
import os
import json
import uuid
import boto3
import requests
from datetime import datetime

lambda_client = boto3.client('lambda')
s3 = boto3.client('s3')

SLEEPER_URL_TEMPLATE = "https://api.sleeper.app/v1/players/{league}"
LEAGUES = ["nfl", "nba"]
CHUNK_SIZE = int(os.environ.get('CHUNK_SIZE', '1000'))
CHUNK_LAMBDA_NAME = os.environ.get('CHUNK_LAMBDA_NAME', 'sleeper_chunk_processor')
S3_BUCKET = os.environ.get('S3_BUCKET', 'vsnandy-sleeper-player-data')

def handler(event, context):
    for league in LEAGUES:
        print(f"🔄 Fetching {league.upper()} player data...")
        resp = requests.get(SLEEPER_URL_TEMPLATE.format(league=league), timeout=90)
        if resp.status_code != 200:
            print(f"❌ Failed to fetch {league}: {resp.status_code}")
            continue

        players = resp.json()
        print(f"✅ Retrieved {len(players)} {league.upper()} players.")

        # --- S3 snapshot logic ---
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
        s3_key = f"players/{league}/snapshot_{timestamp}.json"
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(players),
            ContentType="application/json"
        )
        print(f"💾 Saved {league.upper()} snapshot → s3://{S3_BUCKET}/{s3_key}")
        # --- snapshot done ---

        # Now split into chunks and invoke processing
        items = list(players.items())  # convert dict to list of (player_id, data)
        total = len(items)
        chunk_count = 0

        for i in range(0, total, CHUNK_SIZE):
            chunk_items = items[i:i + CHUNK_SIZE]
            payload = {
                "league": league,
                "chunkId": str(uuid.uuid4()),
                "items": chunk_items
            }
            print(f"➡️ Invoking chunk processor for {league}, chunk #{chunk_count}, size={len(chunk_items)}")
            lambda_client.invoke(
                FunctionName=CHUNK_LAMBDA_NAME,
                InvocationType='Event',  # async invocation
                Payload=json.dumps(payload)
            )
            chunk_count += 1

        print(f"🚀 Dispatched {chunk_count} chunks for league {league}")

    return {
        "statusCode": 200,
        "body": json.dumps({"message": "Chunks dispatched"})
    }
