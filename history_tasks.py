"""Importable RQ job functions. Must be on the RQ worker's Python path."""
from history_sync import import_woof


def import_woof_task(url, woof_id, table, years, cutoff, batch_size):
    return import_woof(url=url, woof_id=woof_id, table=table,
                       years=years, cutoff=cutoff, batch_size=batch_size)
