"""
Queue-aware woof synchronization logic.

Design goal:
  * live queue: newest entries needed by the UI
  * dispatch queue: small planning jobs that inspect DB holes
  * backfill queue: bounded historical repair jobs

This module is intended to replace the scheduling/loading parts of utils.py:
  * run_jobs
  * enqueue_woof_load_jobs
  * load_woof

It does not change the frontend API shape. Existing callers can call run_jobs().
"""

from __future__ import annotations

import os
import time
import traceback
from datetime import datetime
from typing import Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError

import cspot_utils
from db import db_session
from models import Woofs, WoofData
from redis_config import redis_conn, live_q, dispatch_q, backfill_q
import tasks as tasks

# Tunables. Override with env vars during experiments.
MAX_WOOF_ELES = int(os.environ.get("WOOFPLOT_MAX_WOOF_ELES", "10000"))
LOOKBACK_WINDOW = int(os.environ.get("WOOFPLOT_LOOKBACK_WINDOW", "9800"))
SMALL_JOB = int(os.environ.get("WOOFPLOT_SMALL_JOB", "20"))
BACKFILL_CHUNK_SIZE = int(os.environ.get("WOOFPLOT_BACKFILL_CHUNK", "200"))
MAX_BACKFILL_JOBS_PER_PASS = int(os.environ.get("WOOFPLOT_MAX_BACKFILL_JOBS_PER_PASS", "10"))
DEDUP_TTL_SECONDS = int(os.environ.get("WOOFPLOT_DEDUP_TTL_SECONDS", str(24 * 3600)))
JOB_TIMEOUT_SECONDS = int(os.environ.get("WOOFPLOT_JOB_TIMEOUT_SECONDS", "120"))
DEBUG = os.environ.get("WPDEBUG", "false").lower() in ("1", "true", "yes")


def log(msg: str) -> None:
    print(msg, flush=True)

def cspot_get_earliest_seqno(url):
    ''' Returns the earliest seqno from url or -1 on error '''
    failed = True
    exc = val = None
    try:
        val, code, err = cspot_utils.senspot_get_earliest_seqno(url)
        if val != b"":
            failed = False
    except Exception as e:  # keep retry policy in caller
        exc = e
    
    if val is None:
        failed = True
    else:
        err_strings = ["ServerRequest", "WooFGet", "failed", "error", "Error", "ERROR"]
        err_bytes = [s.encode("utf-8") for s in err_strings]
        if any(substring in val for substring in err_bytes):
            failed = True
    if failed:
        if DEBUG:
            log(f"cspot_get_earliest_seqno failed url={url} code={code} exc={exc} val={val}")
        return -1

    retn = int(val.decode("utf-8").strip())
    return retn

def cspot_get(url: str, seqno: int = -1):
    """Return (result_fields, True) or (message, False)."""
    failed = True
    exc = val = None
    try:
        retn, code, err = cspot_utils.senspot_get(url, seqno=seqno)
        val = retn
        if val != b"":
            failed = False
    except Exception as e:  # keep retry policy in caller
        exc = e

    if val is None:
        failed = True
    else:
        err_strings = ["ServerRequest", "WooFGet", "failed", "error", "Error", "ERROR"]
        err_bytes = [s.encode("utf-8") for s in err_strings]
        if any(substring in val for substring in err_bytes):
            failed = True

    if failed:
        if DEBUG:
            log(f"cspot_get failed url={url} seqno={seqno} exc={exc} val={val}")
        return {"WOOFPLOT": f"cspot_get failed url={url} seqno={seqno} exc={exc}"}, False

    return val.decode("utf-8").strip().split(" "), True


def cspot_get_retry(url: str, seqno: int = -1, retries: int = 1, sleep_s: float = 0.5):
    for attempt in range(retries + 1):
        res, ok = cspot_get(url, seqno=seqno)
        if ok:
            return res, True
        if attempt < retries:
            time.sleep(sleep_s)
    return res, False


def parse_cspot_result(res: Sequence[str], expected_seqno: Optional[int] = None):
    """Parse the senspot result format used by current utils.py.

    Expected shape appears to be:
      value time: epoch host seq_no: seqno
    where value is res[0], epoch is res[2], seqno is res[5].
    """
    data = res[0].strip()
    epoch = float(res[2])
    seqno = int(res[5])
    if expected_seqno is not None and seqno != int(expected_seqno):
        # Do not fail hard; log so wrapped Woofs / cspot behavior are visible.
        log(f"WARNING parse_cspot_result expected seqno={expected_seqno}, got seqno={seqno}")
    return datetime.fromtimestamp(epoch), seqno, data


def get_woof_url_from_id(woof_id: int) -> Optional[str]:
    row = db_session.query(Woofs.url).filter(Woofs.id == woof_id).first()
    return row[0] if row else None


def get_woof_id_from_url(url: str) -> Optional[int]:
    row = db_session.query(Woofs.id).filter(Woofs.url == url).first()
    return row[0] if row else None


def get_or_create_woof(url: str) -> Woofs:
    woof = db_session.query(Woofs).filter(Woofs.url == url).first()
    if woof is not None:
        return woof
    woof = Woofs(url=url, name="woofname", latest_seq_no=-1)
    db_session.add(woof)
    db_session.commit()
    return woof


def get_latest_seqno_from_remote(url: str) -> Optional[int]:
    res, ok = cspot_get_retry(url, seqno=-1, retries=1)
    if not ok:
        return None
    return int(res[5])


def reserve_once(key: str, ttl: int = DEDUP_TTL_SECONDS) -> bool:
    return redis_conn.set(key, "1", nx=True, ex=ttl) is True


def release_reservation(key: str) -> None:
    redis_conn.delete(key)


def find_missing_ranges(woof_id: int, start_seq: int, end_seq: Optional[int] = None) -> List[Tuple[int, int]]:
    """Find missing seqno ranges in [start_seq, end_seq].

    This keeps the previous window-function approach but also handles the case
    where the DB has no rows in the window: that whole window is missing.
    """
    q = db_session.query(WoofData.seqno).filter(WoofData.woof_id == woof_id, WoofData.seqno >= start_seq)
    if end_seq is not None:
        q = q.filter(WoofData.seqno <= end_seq)
    have = [int(x[0]) for x in q.order_by(WoofData.seqno).all()]

    if end_seq is None:
        if not have:
            return []
        end_seq = max(have)

    if not have:
        return [(int(start_seq), int(end_seq))] if start_seq <= end_seq else []

    gaps: List[Tuple[int, int]] = []
    cursor = int(start_seq)
    for seq in have:
        if seq > cursor:
            gaps.append((cursor, seq - 1))
        cursor = seq + 1
    if cursor <= int(end_seq):
        gaps.append((cursor, int(end_seq)))
    return gaps


def split_ranges_desc(ranges: Iterable[Tuple[int, int]], max_span: int) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    for a, b in ranges:
        x = int(b)
        while x >= int(a):
            y = max(int(a), x - max_span + 1)
            out.append((y, x))
            x = y - 1
    return out


def enqueue_live_load(woof_id: int, url: str, latest_seqno: int, *, count: int = SMALL_JOB):
    key = f"woofplot:live:{woof_id}:{latest_seqno}:{count}"
    if not reserve_once(key):
        if DEBUG:
            log(f"LIVE duplicate key={key}")
        return None
    try:
        job = live_q.enqueue(
            tasks.load_woof_tail_task,
            woof_id,
            url,
            int(latest_seqno),
            int(count),
            job_timeout=JOB_TIMEOUT_SECONDS,
            result_ttl=3600,
            failure_ttl=86400,
        )
        log(f"ENQUEUED live job={job.id} woof_id={woof_id} latest={latest_seqno} count={count}")
        return job
    except Exception:
        release_reservation(key)
        raise


def enqueue_backfill_plan(woof_id: int, url: str, latest_seqno: int):
    key = f"woofplot:dispatch:{woof_id}:{latest_seqno}"
    if not reserve_once(key):
        if DEBUG:
            log(f"DISPATCH duplicate key={key}")
        return None
    try:
        job = dispatch_q.enqueue(
            tasks.plan_backfill_task,
            woof_id,
            url,
            int(latest_seqno),
            job_timeout=JOB_TIMEOUT_SECONDS,
            result_ttl=3600,
            failure_ttl=86400,
        )
        log(f"ENQUEUED dispatch job={job.id} woof_id={woof_id} latest={latest_seqno}")
        return job
    except Exception:
        release_reservation(key)
        raise


def enqueue_backfill_range(woof_id: int, url: str, start_seq: int, end_seq: int, *, reason: str = "backfill"):
    key = f"woofplot:backfill:{woof_id}:{start_seq}:{end_seq}"
    if not reserve_once(key):
        if DEBUG:
            log(f"BACKFILL duplicate key={key}")
        return None
    try:
        job = backfill_q.enqueue(
            tasks.load_woof_range_task,
            woof_id,
            url,
            int(start_seq),
            int(end_seq),
            reason,
            job_timeout=JOB_TIMEOUT_SECONDS,
            result_ttl=3600,
            failure_ttl=86400,
        )
        if DEBUG:
            log(f"ENQUEUED backfill job={job.id} woof_id={woof_id} range={start_seq}..{end_seq}")
        return job
    except Exception:
        release_reservation(key)
        raise


def refresh_woof(woof_id: int, url: Optional[str] = None, *, live_count: int = SMALL_JOB):
    """Fast API-side entrypoint: discover latest and enqueue live + dispatch work."""
    if url is None:
        url = get_woof_url_from_id(woof_id)
    if not url:
        log(f"refresh_woof: no url found for woof_id={woof_id}")
        return {"ok": False, "error": "missing url"}

    latest = get_latest_seqno_from_remote(url)
    if latest is None:
        log(f"refresh_woof: remote latest unavailable for woof_id={woof_id} url={url}")
        return {"ok": False, "error": "remote latest unavailable"}

    enqueue_live_load(woof_id, url, latest, count=live_count)
    enqueue_backfill_plan(woof_id, url, latest)
    return {"ok": True, "woof_id": woof_id, "url": url, "latest": latest}


def run_jobs(woofId: int, limit: int = -1, wurl: Optional[str] = None):
    """Compatibility replacement for utils.run_jobs().

    limit == -1: schedule live tail + bounded backfill planner.
    limit  > 0: schedule older historical work ahead of current earliest DB seqno.
    """
    try:
        url = wurl if wurl is not None else get_woof_url_from_id(woofId)
        if not url:
            log(f"run_jobs: no url found for woofId={woofId}")
            return None

        if limit == -1:
            return refresh_woof(woofId, url)

        earliest = db_session.query(func.min(WoofData.seqno)).filter(WoofData.woof_id == woofId).scalar()
        if earliest is None:
            return refresh_woof(woofId, url)
        end_seq = int(earliest) - 1
        start_seq = max(10, end_seq - int(limit) + 1)
        if start_seq > end_seq:
            log(f"run_jobs: nothing older to load woofId={woofId} earliest={earliest} limit={limit}")
            return {"ok": True, "enqueued": 0}
        job = enqueue_backfill_range(woofId, url, start_seq, end_seq, reason="older")
        return {"ok": True, "enqueued": 1 if job else 0, "range": (start_seq, end_seq)}
    except Exception as e:
        log(f"Exception in run_jobs: {e}")
        traceback.print_exc()
        return None


def plan_backfill_jobs(
    woof_id: int,
    url: str,
    latest_seqno: int,
    *,
    pass_no: int = 1,
    chunk_size: int = BACKFILL_CHUNK_SIZE,
    max_jobs: int = MAX_BACKFILL_JOBS_PER_PASS,
):
    """Find holes near the live window and enqueue only a bounded batch.

    Newest holes are scheduled first. If more remain, a later refresh will pick
    them up; this deliberately avoids a startup queue explosion.
    """
    start_seq = max(10, int(latest_seqno) - LOOKBACK_WINDOW + 1)
    gaps = find_missing_ranges(woof_id, start_seq, int(latest_seqno))
    gaps.sort(key=lambda r: r[1], reverse=True)
    ranges = split_ranges_desc(gaps, int(chunk_size))
    selected = ranges[: int(max_jobs)]

    enqueued = 0
    for start, end in selected:
        if enqueue_backfill_range(woof_id, url, start, end):
            enqueued += 1

    remaining = max(0, len(ranges) - len(selected))
    log(
        f"PLAN_BACKFILL woof_id={woof_id} latest={latest_seqno} "
        f"gaps={len(gaps)} jobs_total={len(ranges)} enqueued={enqueued} remaining={remaining}"
    )
    return {"ok": True, "gaps": len(gaps), "jobs_total": len(ranges), "enqueued": enqueued, "remaining": remaining}


def existing_seqnos(woof_id: int, start_seq: int, end_seq: int) -> set[int]:
    rows = (
        db_session.query(WoofData.seqno)
        .filter(WoofData.woof_id == woof_id, WoofData.seqno >= start_seq, WoofData.seqno <= end_seq)
        .all()
    )
    return {int(r[0]) for r in rows}


def load_woof_tail(woof_id: int, url: str, latest_seqno: int, *, count: Optional[int] = None):
    if count is None:
        count = SMALL_JOB
    end_seq = int(latest_seqno)
    start_seq = max(1, end_seq - int(count) + 1)
    return load_woof_range(woof_id, url, start_seq, end_seq, reason="live")


def load_woof_range(woof_id: int, url: str, start_seq: int, end_seq: int, *, reason: str = "backfill"):
    """Load an inclusive seqno range idempotently, committing once per range."""
    start_seq = int(start_seq)
    end_seq = int(end_seq)
    earliest = cspot_get_earliest_seqno(url)
    if earliest != -1: #else the cspot call failed for some reason
        if earliest > end_seq:
            log(f"SKIP stale backfill woof_id={woof_id} range={start_seq}..{end_seq} remote_earliest={earliest}")
            return None
        if earliest > start_seq:
            start_seq = earliest

    if start_seq <= 0 or end_seq < start_seq:
        log(f"load_woof_range: invalid range woof_id={woof_id} range={start_seq}..{end_seq} (earliest: {earliest})")
        return None

    woof = db_session.query(Woofs).filter(Woofs.id == woof_id).first()
    if woof is None:
        woof = get_or_create_woof(url)
        woof_id = woof.id

    already_have = existing_seqnos(woof_id, start_seq, end_seq)
    rows: List[WoofData] = []
    last = None
    misses = 0

    for seqno in range(start_seq, end_seq + 1):
        if seqno in already_have:
            continue
        res, ok = cspot_get_retry(url, seqno=seqno, retries=1)
        if not ok:
            misses += 1
            log(f"load_woof_range: cspot failed woof_id={woof_id} seqno={seqno} reason={reason}")
            continue
        ts, returned_seqno, data = parse_cspot_result(res, expected_seqno=seqno)
        row = WoofData(ts=ts, seqno=returned_seqno, data=data, woof=woof)
        rows.append(row)
        last = (ts, returned_seqno, data)

    inserted = 0
    if rows:
        try:
            db_session.add_all(rows)
            if woof.latest_seq_no is None or end_seq > int(woof.latest_seq_no):
                woof.latest_seq_no = end_seq
            db_session.commit()
            inserted = len(rows)
        except IntegrityError as e:
            # With the current schema, uniqueness is on (woof_id, ts), not
            # (woof_id, seqno). Roll back and retry rows one-by-one so a single
            # duplicate timestamp does not poison the whole range.
            log(f"load_woof_range: IntegrityError on batch; retrying row-wise: {e}")
            db_session.rollback()
            inserted = _insert_rows_one_by_one(woof, rows)
            if woof.latest_seq_no is None or end_seq > int(woof.latest_seq_no):
                woof.latest_seq_no = end_seq
            db_session.commit()

    elif woof.latest_seq_no is None or end_seq > int(woof.latest_seq_no):
        woof.latest_seq_no = end_seq
        db_session.commit()

    log(
        f"LOAD_RANGE done woof_id={woof_id} range={start_seq}..{end_seq} "
        f"reason={reason} inserted={inserted} skipped={len(already_have)} failed={misses}"
    )
    return {
        "ok": True,
        "woof_id": woof_id,
        "start": start_seq,
        "end": end_seq,
        "inserted": inserted,
        "skipped": len(already_have),
        "failed": misses,
        "last": last,
    }


def _insert_rows_one_by_one(woof: Woofs, rows: Sequence[WoofData]) -> int:
    inserted = 0
    for row in rows:
        try:
            # Rebind row to the active woof/session after rollback.
            db_session.add(WoofData(ts=row.ts, seqno=row.seqno, data=row.data, woof=woof))
            db_session.flush()
            inserted += 1
        except IntegrityError:
            db_session.rollback()
            # Make sure the parent woof is attached again after rollback.
            woof = db_session.query(Woofs).filter(Woofs.id == woof.id).first()
            continue
    return inserted
