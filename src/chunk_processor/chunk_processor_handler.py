import os
import time
import boto3
from datetime import datetime
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.client('dynamodb')

TABLE_NAME = os.environ.get('TABLE_NAME', 'sleeper_players')
BATCH_SIZE = 25
MAX_RETRIES = 3

def handler(event, context):
    league = event.get('league')
    chunk_id = event.get('chunkId')
    items = event.get('items', [])   # list of [player_id, data] pairs
    
    logger.info(f"🔧 Processing chunk {chunk_id} for league {league}, {len(items)} items")

    updated_at = datetime.utcnow().isoformat()
    batch = []
    total_written = 0

    for (player_id, data) in items:
        item = {
            'league': {'S': league},
            'player_id': {'S': player_id},
            'full_name': {'S': data.get('full_name','')},
            'team': {'S': data.get('team','') or 'FA'},
            'position': {'S': data.get('position','') or 'UNK'},
            'status': {'S': data.get('status','') or 'unknown'},
            'updated_at': {'S': updated_at}
        }
        batch.append({'PutRequest': {'Item': item}})
        
        if len(batch) == BATCH_SIZE:
            written = _submit_batch(batch)
            total_written += written
            batch = []

    if batch:
        written = _submit_batch(batch)
        total_written += written

    logger.info(f"✅ Finished chunk {chunk_id}: total_written={total_written}")
    return {
        "chunkId": chunk_id,
        "items_processed": len(items),
        "items_written": total_written
    }


def _submit_batch(batch):
    request_items = { TABLE_NAME: batch }
    attempt = 0
    while attempt < MAX_RETRIES:
        attempt += 1
        resp = dynamodb.batch_write_item(RequestItems=request_items)
        unprocessed = resp.get('UnprocessedItems', {})
        processed_count = len(batch) - len(unprocessed.get(TABLE_NAME, []))
        if not unprocessed or attempt == MAX_RETRIES:
            return processed_count
        logger.info(f"⚠️ Retry attempt {attempt}, unprocessed items count: {len(unprocessed.get(TABLE_NAME, []))}")
        time.sleep(0.5 * (2**attempt))
        request_items = unprocessed
    return 0