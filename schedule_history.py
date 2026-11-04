#!/usr/bin/env python3
"""Schedule one RQ history-import job per mapped Woofplot Woof.

Examples:
  python schedule_history.py --mapping woof_tables.json --years 1 --dry-run
  python schedule_history.py --mapping woof_tables.json --years 1 --woof-id 24
  python schedule_history.py --mapping woof_tables.json --years 2
"""
import argparse
import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg2
from dateutil.relativedelta import relativedelta
from redis import Redis
from rq import Queue

from history_sync import load_mapping, source_table, woofplot_dsn


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mapping', required=True)
    p.add_argument('--years', type=int, default=1)
    p.add_argument('--woof-id', type=int)
    p.add_argument('--batch-size', type=int, default=1000)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--redis-url', default='redis://localhost:6379/0')
    p.add_argument('--job-timeout', type=int, default=14400)
    args = p.parse_args()
    if args.years < 1 or args.batch_size < 1:
        p.error('--years and --batch-size must be positive')
    mapping = load_mapping(args.mapping)
    cutoff = (datetime.now(ZoneInfo('America/Los_Angeles')).replace(tzinfo=None)
              - relativedelta(years=args.years)).isoformat()
    with psycopg2.connect(woofplot_dsn()) as conn, conn.cursor() as cur:
        if args.woof_id is None:
            cur.execute('SELECT "woofId", url FROM woofs ORDER BY "woofId"')
        else:
            cur.execute('SELECT "woofId", url FROM woofs WHERE "woofId"=%s', (args.woof_id,))
        woofs = cur.fetchall()
    q = None if args.dry_run else Queue('history', connection=Redis.from_url(args.redis_url))
    counts = dict(woofs=len(woofs), matched=0, skipped=0, enqueued=0, already_present=0)

    for woof_id, url in woofs:
        normalized_url = url.replace("-", "_")
        if "ota_data" in normalized_url or "ota_storm" in normalized_url:
            #skip the ones that don't have a serialized data column (for now)
            print(f"SKIP structured WoofDB source: {url}")
            counts['skipped'] += 1
            continue

        table = source_table(mapping, url)
        if not table:
            counts['skipped'] += 1
            continue
        counts['matched'] += 1
        if args.dry_run:
            print(f'DRY RUN woof_id={woof_id} table={table} url={url}')
            continue
        # One job per Woof; workers stream batches internally. Avoid duplicate
        # concurrent jobs using a stable ID per Woof/year window.
        key = hashlib.sha256(f'{woof_id}|{table}|{args.years}'.encode()).hexdigest()[:24]
        job_id = f'history-{key}'
        existing = q.fetch_job(job_id)
        if existing and existing.get_status(refresh=True) in ('queued', 'started', 'deferred', 'scheduled'):
            counts['already_present'] += 1
            continue
        # Finished/failed jobs need an explicit new ID for safe reruns.
        if existing:
            job_id = f'{job_id}-{datetime.now().strftime("%Y%m%d%H%M%S%f")}'
        q.enqueue('history_tasks.import_woof_task', url, woof_id, table,
                  args.years, cutoff, args.batch_size,
                  job_id=job_id, job_timeout=args.job_timeout,
                  result_ttl=86400, failure_ttl=604800)
        counts['enqueued'] += 1
        print(f'ENQUEUED woof_id={woof_id} table={table}')
    print(json.dumps(counts, indent=2))


if __name__ == '__main__':
    main()
