"""
RQ task wrappers for woofplot.

These functions are intentionally thin. The real logic lives in woof_sync.py so
it can be called directly from tests and from the API without needing a worker.
"""

from datetime import datetime
from rq import get_current_job

import woof_sync


def _job_id() -> str:
    job = get_current_job()
    return job.id if job is not None else "direct-call"


def load_woof_tail_task(woof_id: int, url: str, latest_seqno: int, count: int = None):
    job_id = _job_id()
    print(
        f"load_woof_tail_task [{job_id}] woof_id={woof_id} latest={latest_seqno} "
        f"count={count} url={url} at {datetime.now()}",
        flush=True,
    )
    return woof_sync.load_woof_tail(woof_id, url, latest_seqno, count=count)


def load_woof_range_task(
    woof_id: int,
    url: str,
    start_seqno: int,
    end_seqno: int,
    reason: str = "backfill",
):
    job_id = _job_id()
    print(
        f"load_woof_range_task [{job_id}] woof_id={woof_id} "
        f"range={start_seqno}..{end_seqno} reason={reason} url={url} at {datetime.now()}",
        flush=True,
    )
    return woof_sync.load_woof_range(woof_id, url, start_seqno, end_seqno, reason=reason)


def plan_backfill_task(woof_id: int, url: str, latest_seqno: int, *, pass_no: int = 1):
    job_id = _job_id()
    print(
        f"plan_backfill_task [{job_id}] woof_id={woof_id} latest={latest_seqno} "
        f"pass={pass_no} url={url} at {datetime.now()}",
        flush=True,
    )
    return woof_sync.plan_backfill_jobs(woof_id, url, latest_seqno, pass_no=pass_no)


# Backward-compatible task names. These let you migrate existing enqueues slowly.
def woof_load_task(url, seqno, count, *, woof_id=None, latest=None):
    if woof_id is None:
        woof_id = woof_sync.get_woof_id_from_url(url)
    if seqno == -1:
        if latest is None:
            latest = woof_sync.get_latest_seqno_from_remote(url)
        return load_woof_tail_task(woof_id, url, latest, count)
    start = int(seqno)
    end = int(seqno) + int(count) - 1
    return load_woof_range_task(woof_id, url, start, end, reason="legacy")


def call_enqueue_woof_load_jobs(wid, url, seqno):
    return plan_backfill_task(wid, url, seqno)

def older_backfill_dispatch_task(woof_id, woofurl):
    woof_earliest = woof_sync.cspot_get_earliest_seqno(woofurl)
    if woof_earliest == -1:
        print(
            f"older_backfill_dispatch_task failed: no earliest seqno for {woofurl}",
            flush=True,
        )
        return -1

    return woof_sync.enqueue_older_backfill(
        woof_id,
        woofurl,
        woof_earliest,
        chunk_size=200,
        max_jobs=10,
    )
