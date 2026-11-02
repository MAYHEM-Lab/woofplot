#!/usr/bin/env python3
"""Import one bounded WoofDB sequence range into Woofplot.

Environment:
  WOOFDB_DSN: psycopg2 DSN for the alerts/sensor database
  SQLALCHEMY_DATABASE_URI: Woofplot PostgreSQL URL (postgresql+psycopg2:// accepted)

Example:
  python history_sync.py --mapping woof_tables.json --url 'woof://...' \
      --years 1 --start-seq 1000 --end-seq 1499 --dry-run
"""
import argparse
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values

PACIFIC = ZoneInfo('America/Los_Angeles')


def woofplot_dsn():
    uri = os.environ['SQLALCHEMY_DATABASE_URI']
    return uri.replace('postgresql+psycopg2://', 'postgresql://', 1)


def source_table(mapping_path, url):
    with open(mapping_path, encoding='utf-8') as f:
        mapping = json.load(f)
    entry = mapping.get(url)
    if not entry or not entry.get('tables'):
        raise ValueError(f'No mapped tables for {url}')
    return entry['tables'][-1]


def import_range(*, mapping_path, url, start_seq, end_seq, years=1,
                 cutoff=None, batch_size=1000, dry_run=False):
    if years < 1 or start_seq < 0 or end_seq < start_seq or batch_size < 1:
        raise ValueError('Invalid years, sequence range, or batch size')
    table = source_table(mapping_path, url)
    # One fixed cutoff can be passed to all jobs in the same scheduling run.
    if cutoff is None:
        from dateutil.relativedelta import relativedelta
        cutoff = datetime.now(PACIFIC).replace(tzinfo=None) - relativedelta(years=years)
    if isinstance(cutoff, str):
        cutoff = datetime.fromisoformat(cutoff)
    if cutoff.tzinfo is not None:
        cutoff = cutoff.astimezone(PACIFIC).replace(tzinfo=None)

    source_dsn = os.environ['WOOFDB_DSN']
    stats = {'table': table, 'read': 0, 'inserted': 0, 'cutoff': cutoff.isoformat()}
    with psycopg2.connect(source_dsn) as source, psycopg2.connect(woofplot_dsn()) as dest:
        with dest.cursor() as cur:
            cur.execute('SELECT "woofId" FROM woofs WHERE url = %s', (url,))
            result = cur.fetchone()
            if not result:
                raise ValueError(f'Woof not registered in Woofplot: {url}')
            woof_id = result[0]
        # Validate source table existence and columns; identifiers are safely quoted.
        with source.cursor() as cur:
            cur.execute('''SELECT column_name FROM information_schema.columns
                           WHERE table_schema='public' AND table_name=%s''', (table,))
            cols = {row[0] for row in cur.fetchall()}
            if not {'seqno', 'dt', 'data'} <= cols:
                raise ValueError(f'Unexpected schema or missing table: {table}')
            query = sql.SQL('''SELECT seqno, dt, data FROM {}.{}
                             WHERE seqno BETWEEN %s AND %s AND dt >= %s
                             ORDER BY seqno''').format(sql.Identifier('public'), sql.Identifier(table))
            cur.execute(query, (start_seq, end_seq, cutoff))
            while True:
                rows = cur.fetchmany(batch_size)
                if not rows:
                    break
                stats['read'] += len(rows)
                values = []
                for seqno, dt, data in rows:
                    if dt is None or data is None:
                        continue
                    # Source is naive Pacific local time; DST repeated-hour ambiguity
                    # cannot be resolved from this column alone.
                    aware_dt = dt.replace(tzinfo=PACIFIC)
                    values.append((woof_id, int(seqno), aware_dt, str(data)))
                if not values or dry_run:
                    continue
                with dest.cursor() as out:
                    execute_values(out, '''INSERT INTO woofdata (woof_id, seqno, ts, data)
                        VALUES %s ON CONFLICT (woof_id, seqno) DO NOTHING''',
                        values, page_size=batch_size)
                    stats['inserted'] += out.rowcount
                dest.commit()
    return stats


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mapping', required=True)
    p.add_argument('--url', required=True)
    p.add_argument('--start-seq', type=int, required=True)
    p.add_argument('--end-seq', type=int, required=True)
    p.add_argument('--years', type=int, default=1)
    p.add_argument('--cutoff', help='ISO local datetime; fixes boundary across jobs')
    p.add_argument('--batch-size', type=int, default=1000)
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    result = import_range(mapping_path=args.mapping, url=args.url,
                          start_seq=args.start_seq, end_seq=args.end_seq,
                          years=args.years, cutoff=args.cutoff,
                          batch_size=args.batch_size, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
