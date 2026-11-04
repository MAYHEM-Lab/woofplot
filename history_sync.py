#!/usr/bin/env python3
"""Import one Woof's recent history from WoofDB to Woofplot.

Requires WOOFDB_DSN and SQLALCHEMY_DATABASE_URI environment variables.
Source dt is assumed to be Pacific local wall-clock time.
"""
import argparse
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values
from dateutil.relativedelta import relativedelta

PACIFIC = ZoneInfo('America/Los_Angeles')


def woofplot_dsn():
    return os.environ['SQLALCHEMY_DATABASE_URI'].replace('postgresql+psycopg2://', 'postgresql://', 1)


def load_mapping(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def source_table(mapping, url):
    entry = mapping.get(url)
    if not entry or not entry.get('tables'):
        return None
    return entry['tables'][-1]


def import_woof(*, url, woof_id, table, years=1, cutoff=None, batch_size=1000, dry_run=False):
    if years < 1 or batch_size < 1:
        raise ValueError('years and batch_size must be positive')
    if cutoff is None:
        cutoff = datetime.now(PACIFIC).replace(tzinfo=None) - relativedelta(years=years)
    if isinstance(cutoff, str):
        cutoff = datetime.fromisoformat(cutoff)
    if cutoff.tzinfo is not None:
        cutoff = cutoff.astimezone(PACIFIC).replace(tzinfo=None)
    stats = dict(url=url, woof_id=woof_id, table=table, cutoff=cutoff.isoformat(), read=0, inserted=0)
    with psycopg2.connect(os.environ['WOOFDB_DSN']) as source, psycopg2.connect(woofplot_dsn()) as dest:
        with dest.cursor() as cur:
            cur.execute('SELECT "woofId" FROM woofs WHERE "woofId"=%s AND url=%s', (woof_id, url))
            if not cur.fetchone():
                raise ValueError(f'Woof ID/URL mismatch: {woof_id} {url}')
        with source.cursor() as cur:
            cur.execute('''SELECT column_name FROM information_schema.columns
                           WHERE table_schema='public' AND table_name=%s''', (table,))
            if not {'seqno', 'dt', 'data'} <= {r[0] for r in cur.fetchall()}:
                raise ValueError(f'Missing source table or columns: {table}')
        # Server-side cursor prevents the entire year's data being buffered in RAM.
        # Query is read-only and source transaction remains open for this Woof.
        with source.cursor(name='woof_history_stream') as cur:
            cur.itersize = batch_size
            query = sql.SQL('''SELECT seqno, dt, data FROM {}.{}
                             WHERE dt >= %s AND dt IS NOT NULL AND data IS NOT NULL
                             ORDER BY seqno''').format(sql.Identifier('public'), sql.Identifier(table))
            cur.execute(query, (cutoff,))
            while True:
                rows = cur.fetchmany(batch_size)
                if not rows:
                    break
                stats['read'] += len(rows)
                if dry_run:
                    continue
                values = [(woof_id, int(seqno), dt.replace(tzinfo=PACIFIC), str(data))
                          for seqno, dt, data in rows]
                with dest.cursor() as out:
                    execute_values(out, '''INSERT INTO woofdata (woof_id, seqno, ts, data)
                        VALUES %s ON CONFLICT (woof_id, ts) DO NOTHING''',
                        values, page_size=batch_size)
                    stats['inserted'] += out.rowcount
                dest.commit()
    return stats


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--mapping', required=True)
    p.add_argument('--url', required=True)
    p.add_argument('--woof-id', type=int, required=True)
    p.add_argument('--years', type=int, default=1)
    p.add_argument('--batch-size', type=int, default=1000)
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    table = source_table(load_mapping(args.mapping), args.url)
    if not table:
        p.error('URL not present in mapping')
    print(json.dumps(import_woof(url=args.url, woof_id=args.woof_id, table=table,
          years=args.years, batch_size=args.batch_size, dry_run=args.dry_run), indent=2))


if __name__ == '__main__':
    main()
