import json
import os
import time
import boto3
import requests
from datetime import datetime

s3 = boto3.client('s3')
dynamodb = boto3.client('dynamodb')

S3_BUCKET = os.environ.get('S3_BUCKET', 'sleeper-player-data')
TABLE_NAME = os.environ.get('TABLE_NAME', 'sleeper_players')
LEAGUES = ["nfl", "nba"]  # Expandable list


def handler(event, context):
    start_time = time.time()
    total_updated = 0

    for league in LEAGUES:
        print(f"🔄 Fetching {league.upper()} player data...")
        url = f"https://api.sleeper.app/v1/players/{league}"
        response = requests.get(url, timeout=90)
        if response.status_code != 200:
            print(f"❌ Failed to fetch {league}: {response.status_code}")
            continue

        players = response.json()
        print(f"✅ Retrieved {len(players)} {league.upper()} players.")

        # Save snapshot to S3
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
        s3_key = f"players/{league}/snapshot_{timestamp}.json"
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(players),
            ContentType="application/json"
        )
        print(f"💾 Saved {league.upper()} snapshot → s3://{S3_BUCKET}/{s3_key}")

        # Write parsed data to DynamoDB
        updated = _write_players_to_dynamo(players, league)
        total_updated += updated
        print(f"✅ Updated {updated} {league.upper()} players in DynamoDB.")

    print(f"🏁 Done! Total players updated: {total_updated}")
    print(f"⏱ Runtime: {time.time() - start_time:.2f}s")
    return {"statusCode": 200, "body": json.dumps({"total_updated": total_updated})}


def _write_players_to_dynamo(players, league):
    updated_at = datetime.utcnow().isoformat()
    batch = []
    total_written = 0

    for player_id, data in players.items():
        item = {
            'league': {'S': league},
            'player_id': {'S': player_id},
            'full_name': {'S': data.get('full_name', '')},
            'team': {'S': data.get('team', '') or 'FA'},
            'position': {'S': data.get('position', '') or 'UNK'},
            'status': {'S': data.get('status', '') or 'unknown'},
            'updated_at': {'S': updated_at},
        }
        batch.append({'PutRequest': {'Item': item}})

        if len(batch) == 25:
            _write_batch(batch)
            total_written += len(batch)
            batch = []

    if batch:
        _write_batch(batch)
        total_written += len(batch)

    return total_written


def _write_batch(batch):
    """Helper to write 25 DynamoDB items with retries."""
    request = {TABLE_NAME: batch}
    while True:
        response = dynamodb.batch_write_item(RequestItems=request)
        unprocessed = response.get('UnprocessedItems', {})
        if not unprocessed:
            break
        print(f"⚠️ Retrying {len(unprocessed.get(TABLE_NAME, []))} unprocessed items...")
        time.sleep(2)
        request = unprocessed
