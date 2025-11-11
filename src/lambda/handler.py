import json
import os
import time
import boto3
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client('s3')
dynamodb = boto3.client('dynamodb')

S3_BUCKET = os.environ.get('S3_BUCKET', 'vsnandy-sleeper-player-data')
TABLE_NAME = os.environ.get('TABLE_NAME', 'sleeper_players')
LEAGUES = ["nfl", "nba"]
MAX_BATCH_SIZE = 25
MAX_WORKERS = 10  # tune based on memory + write capacity


def handler(event, context):
    start_time = time.time()
    total_updated = 0

    for league in LEAGUES:
        logger.info(f"🔄 Fetching {league.upper()} player data...")
        url = f"https://api.sleeper.app/v1/players/{league}"
        response = requests.get(url, timeout=90)
        if response.status_code != 200:
            logger.info(f"❌ Failed to fetch {league}: {response.status_code}")
            continue

        players = response.json()
        logger.info(f"✅ Retrieved {len(players)} {league.upper()} players.")

        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
        s3_key = f"players/{league}/snapshot_{timestamp}.json"
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(players),
            ContentType="application/json"
        )
        logger.info(f"💾 Saved {league.upper()} snapshot → s3://{S3_BUCKET}/{s3_key}")

        updated = _write_players_to_dynamo_parallel(players, league)
        total_updated += updated
        logger.info(f"✅ Updated {updated} {league.upper()} players in DynamoDB.")

    elapsed = time.time() - start_time
    logger.info(f"🏁 Done! Total players updated: {total_updated}")
    logger.info(f"⏱ Runtime: {elapsed:.2f}s")
    return {"statusCode": 200, "body": json.dumps({"total_updated": total_updated, "duration_s": elapsed})}


def _write_players_to_dynamo_parallel(players, league):
    updated_at = datetime.utcnow().isoformat()
    # Build list of batches
    batches = []
    current = []
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
        current.append({'PutRequest': {'Item': item}})
        if len(current) == MAX_BATCH_SIZE:
            batches.append(current)
            current = []
    if current:
        batches.append(current)

    logger.info(f"Batches to process {len(batches)}.")

    total_written = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_submit_batch, batch): batch for batch in batches}
        for future in as_completed(futures):
            count = future.result()
            total_written += count
            logger.info(f"Total written items at {total_written}.")

    return total_written


def _submit_batch(batch):
    max_retries = 3
    attempt = 0
    request_items = {TABLE_NAME: batch}
    while attempt < max_retries:
        attempt += 1
        response = dynamodb.batch_write_item(RequestItems=request_items)
        unprocessed = response.get('UnprocessedItems', {})
        # count processed items = batch size minus unprocessed
        processed_count = len(batch) - len(unprocessed.get(TABLE_NAME, []))
        if not unprocessed or attempt == max_retries:
            return processed_count
        # retry logic
        request_items = unprocessed
        time.sleep(0.5 * (2**attempt))  # exponential backoff
    return 0
