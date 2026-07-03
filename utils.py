# utils.py
'''
    Author: Chandra Krintz,
    License: UCSB BSD -- see LICENSE file in this repository

    Refactored queue/load path for woofplot.

    This file keeps the public utility/API functions used by routes.py, but
    delegates Woof synchronization to woof_sync.py, which separates live,
    dispatch, and backfill work into different RQ queues.
'''

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from typing import Any, Iterable, Optional

import pytz
from passlib.hash import sha256_crypt
from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

import db
import woof_sync
from db import db_session
from models import Users, Woofs, Columns, WoofData, State

# Queue config is imported for backward compatibility with code/tests that
# expect utils.redis_conn or utils.queue to exist. New scheduling uses
# woof_sync.{live_q,dispatch_q,backfill_q}.
try:
    from redis_config import queue, redis_conn, live_q, dispatch_q, backfill_q
except Exception:  # pragma: no cover - fallback for partial deployment
    from redis_config import queue, redis_conn
    live_q = dispatch_q = backfill_q = queue

MAX_WOOF_ELES = int(os.environ.get("WOOFPLOT_MAX_WOOF_ELES", "10000"))
JOB_LIMIT = int(os.environ.get("WOOFPLOT_BACKFILL_CHUNK", "200"))
SMALL_JOB = int(os.environ.get("WOOFPLOT_SMALL_JOB", "20"))
DEDUP_TTL_SECONDS = int(os.environ.get("WOOFPLOT_DEDUP_TTL_SECONDS", str(24 * 3600)))
ACTIVE_OLDER_TTL_SECONDS = 5 * 60

DEBUG = os.environ.get("WPDEBUG", "false").lower() in ("true", "1", "yes")
if DEBUG:
    print("turning on DEBUG mode!", flush=True)

secsmap = {
    # Kept as-is from the existing code. Note: "minute" currently maps to 300.
    "minute": 300,
    "hour": 3600,
    "day": 86400,
    "week": 604800,
    "moment": -1,
}
PacTZ = pytz.timezone("US/Pacific")


def _log(msg: str) -> None:
    print(msg, flush=True)


################
# Queue/sync compatibility wrappers
################

def find_missing_ranges(woof_id: int, start_seq: int, end_seq: Optional[int] = None):
    return woof_sync.find_missing_ranges(woof_id, start_seq, end_seq=end_seq)


def split_ranges(ranges: Iterable[tuple[int, int]], max_span: int):
    out = []
    for a, b in ranges:
        x = int(a)
        while x <= int(b):
            y = min(x + int(max_span) - 1, int(b))
            out.append((x, y))
            x = y + 1
    return out


def split_ranges_desc(ranges: Iterable[tuple[int, int]], max_span: int):
    return woof_sync.split_ranges_desc(ranges, max_span)


def call_enqueue_woof_load_jobs(woof_id: int, woofurl: str, cspot_seqno: int):
    return enqueue_woof_load_jobs(woof_id, woofurl, cspot_seqno)


def enqueue_woof_load_jobs(woof_id: int, woofurl: str, cspot_seqno: int, *, chunk_size: int = JOB_LIMIT):
    """Compatibility wrapper for old dispatcher jobs.

    New behavior: schedule only a bounded pass of backfill jobs on the backfill
    queue instead of flooding a single FIFO queue with all gaps at once.
    """
    return woof_sync.plan_backfill_jobs(
        woof_id,
        woofurl,
        cspot_seqno,
        chunk_size=chunk_size,
    )


def run_jobs(woofId: int, limit: int = -1, wurl: Optional[str] = None):
    """Queue Woof work without blocking the API.

    limit == -1:
        Enqueue live tail load + bounded backfill planning.
    limit > 0:
        Enqueue one older historical range before the earliest DB seqno.
    """
    return woof_sync.run_jobs(woofId, limit=limit, wurl=wurl)


def call_run_jobs(woofurl, limit=JOB_LIMIT):
    wid = get_woof_id_from_url(woofurl)
    if wid is None:
        woof = get_woof_from_db(woofurl)
        wid = woof.id if woof else None
    if wid is None:
        _log(f"call_run_jobs: unable to resolve woof id for url={woofurl}")
        return None
    return run_jobs(wid, limit, woofurl)


def load_woof(woofurl: str, endsn: int = -1, count: int = SMALL_JOB):
    """Backward-compatible direct loader.
    Existing tasks call load_woof(url, -1, count) for latest-tail loads and
    load_woof(url, end_seq, count) for ranges. The new implementation delegates
    to woof_sync.load_woof_tail/load_woof_range and commits per range.
    """
    woof = get_woof_from_db(woofurl)
    if woof is None:
        return None

    if endsn == -1:
        latest = woof_sync.get_latest_seqno_from_remote(woofurl)
        if latest is None:
            _log(f"load_woof: unable to fetch remote latest for {woofurl}")
            return None
        retn = woof_sync.load_woof_tail(woof.id, woofurl, latest, count=count)
        if retn is not none:
            maybe_enqueue_active_older_backfill(woof.id, woofurl)
        return retn

    end_seq = int(endsn)
    start_seq = max(1, end_seq - int(count) + 1)
    return woof_sync.load_woof_range(woof.id, woofurl, start_seq, end_seq, reason="direct")


def cspot_get(url, seqno=-1):
    return woof_sync.cspot_get(url, seqno=seqno)


################
# Query helpers used by API routes
################

def maybe_enqueue_active_older_backfill(woof_id, woofurl):
    key = f"woofload:older:active:dispatch:{woof_id}"

    if redis_conn.set(key, "1", nx=True, ex=ACTIVE_OLDER_TTL_SECONDS):
        dispatch_q.enqueue(
            tasks_refactor.older_backfill_dispatch_task,
            woof_id,
            woofurl,
        )

def enqueue_older_backfill(
    woof_id: int,
    woofurl: str,
    woof_earliest_seqno: int,
    *,
    chunk_size: int = 200,
    max_jobs: int = 10,
):
    db_earliest = get_earliest_seqno_from_woofId(woof_id)

    if db_earliest == -1:
        return 0

    if db_earliest <= woof_earliest_seqno:
        return 0

    enqueued = 0
    end_seq = db_earliest - 1

    while end_seq >= woof_earliest_seqno and enqueued < max_jobs:
        start_seq = max(woof_earliest_seqno, end_seq - chunk_size + 1)

        job = enqueue_backfill_range(
            woof_id,
            woofurl,
            start_seq,
            end_seq,
            reason="older-backfill",
        )

        if job is not None:
            enqueued += 1

        end_seq = start_seq - 1

    return enqueued

def decimate(lst, target_count):
    if target_count is None or int(target_count) <= 0:
        return lst
    step = max(1, len(lst) // int(target_count))
    return lst[::step]


def get_woof_values(woofId, field, s, e, agg, interval, raw=None):
    """Return Woof values between millisecond timestamps s and e.

    The query path stays DB-first. On a miss, it schedules a live refresh rather
    than allowing a frontend request to create a large synchronous backfill.
    """
    start = s / 1000
    startdt = datetime.fromtimestamp(start, tz=PacTZ)
    end = e / 1000
    enddt = datetime.fromtimestamp(end, tz=PacTZ)
    timediff = end - start
    div = secsmap[interval]
    count_to_return = int(raw) if raw else int(timediff / div) if div > 0 else 1

    responses = []
    if DEBUG:
        _log(f"get_woof_values: {woofId}, field={field}, {startdt}..{enddt}, agg={agg}, interval={interval}, raw={raw}")
        _log(f"\tcount_to_return={count_to_return}")
        wurl = get_woof_url_from_id(woofId)

    try:
        wurl = get_woof_url_from_id(woofId)
        rand_rows = (
            db_session.query(WoofData)
            .filter(and_(WoofData.woof_id == woofId, WoofData.ts >= startdt, WoofData.ts <= enddt))
            .order_by(WoofData.ts)
            .all()
        )

        if len(rand_rows) == 0:
            # Do not block the API on a potentially expensive repair. Schedule
            # live/backfill work and let the next frontend refresh pick it up.
            if wurl:
                run_jobs(woofId, -1, wurl)
            if DEBUG:
                _log(f"\tget_woof_values: no rows; scheduled refresh for woofId={woofId}")
            return [], 200

        retn_len = len(rand_rows)
        if DEBUG:
            _log(f"\tquery returned {retn_len} rows: {rand_rows[0].ts}..{rand_rows[-1].ts}")

        results = [rand_rows[0]]
        dec_val = int(os.environ.get("DECIMATE_SKIP", "250"))
        if retn_len > dec_val:
            results.extend(decimate(rand_rows[1:-1], count_to_return))
        else:
            results.extend(rand_rows[1:-1])
        if retn_len > 1:
            results.append(rand_rows[-1])

        conv = get_conversion(woofId, field)
        for result in results:
            response = {"woofId": woofId, "field": field}
            val: Any = ""
            try:
                val = float(result.data)
            except (TypeError, ValueError):
                tmpv = result.data.split(":")
                if int(field) >= len(tmpv):
                    # Skip malformed rows for this field rather than failing
                    # the whole query response.
                    continue
                val = tmpv[int(field)]

            if conv and conv != "No conversion":
                val = convert(val, conv)

            response["timestamp"] = int(result.ts.timestamp() * 1000)
            response["value"] = val
            responses.append(response)

        if DEBUG:
            _log(f"RETURNING: woofId={woofId}, responses={len(responses)}")
        return responses, 200

    except Exception as e:
        _log(f"Exception in get_woof_values: {e}")
        traceback.print_exc()
        return {"WOOFPLOT": f"get_woof_values exception {e}"}, 500


################
# Woof metadata / DB helpers
################

def add_or_update_woof_in_db(data, seqno=-1):
    """Add/update Woof metadata and column definitions.

    data keys: url, name, seqno, columns[{field,name,conversion}]
    """
    woofurl = data["url"]
    woof = None
    try:
        woof = db_session.query(Woofs).filter(Woofs.url == woofurl).first()
        if not woof:
            if seqno == -1:
                seqno = data.get("seqno", -1)
            assert seqno != -1
            woof = Woofs(url=woofurl, name=data["name"], latest_seq_no=seqno)
            db_session.add(woof)
            db_session.flush()
            for col in data.get("columns", []):
                db_session.add(
                    Columns(
                        field=col["field"],
                        name=col["name"],
                        conversion=col["conversion"],
                        woof=woof,
                    )
                )
        else:
            woof.name = data["name"]
            if "seqno" in data and data["seqno"] is not None:
                woof.latest_seq_no = data["seqno"]

            current_columns = list(woof.columns)
            by_field = {c.field: c for c in current_columns}
            client_fields = []

            for client_col in data.get("columns", []):
                field = client_col["field"]
                client_fields.append(field)
                curr = by_field.get(field)
                if curr:
                    curr.name = client_col["name"]
                    curr.conversion = client_col["conversion"]
                else:
                    db_session.add(
                        Columns(
                            field=field,
                            name=client_col["name"],
                            conversion=client_col["conversion"],
                            woof=woof,
                        )
                    )

            if client_fields:
                for curr in current_columns:
                    if curr.field not in client_fields:
                        db_session.delete(curr)

        db_session.commit()
    except Exception as e:
        db_session.rollback()
        _log(f"Exception in add_or_update_woof_in_db: {e}")
        traceback.print_exc()
    return woof


def add_woof_to_db(woofurl):
    woof = db_session.query(Woofs).filter(Woofs.url == woofurl).first()
    if woof:
        return woof
    woof = Woofs(url=woofurl, name="woofname", latest_seq_no=-1)
    db_session.add(woof)
    db_session.commit()
    return woof


def get_woof_from_db(url):
    woof = db_session.query(Woofs).filter(Woofs.url == url).first()
    if not woof:
        woof = add_woof_to_db(url)
    return woof


def get_latest_seqno_from_woofId(id):
    retn = db_session.query(Woofs.latest_seq_no).filter(Woofs.id == id).first()
    return retn[0] if retn else None


def get_earliest_seqno_from_woofId(woof_id):
    return db_session.query(func.min(WoofData.seqno)).filter(WoofData.woof_id == woof_id).scalar() or -1


def get_woof_url_from_id(id):
    retn = db_session.query(Woofs.url).filter(Woofs.id == id).first()
    return retn[0] if retn else None


def get_woof_id_from_url(url):
    retn = db_session.query(Woofs.id).filter(Woofs.url == url).first()
    return retn[0] if retn else None


def get_woof_entry(woofId, seqno=-1):
    if seqno == -1:
        seqno = get_latest_seqno_from_woofId(woofId)
    return db_session.query(WoofData).filter(WoofData.woof_id == woofId, WoofData.seqno == seqno).first()


def get_conversion(woofId, field):
    retn = db_session.query(Columns).filter_by(woof_id=woofId, field=field).first()
    return retn.conversion if retn else None


def get_all_woof_entries(woofurl):
    woof = get_woof_from_db(woofurl)
    if DEBUG:
        _log(f"get_all_woof_entries {woof}")
    return woof.woofdata


def get_all_woofs_from_db():
    """Return frontend Woof metadata and schedule lightweight refreshes."""
    woofs = db_session.query(Woofs).options(joinedload(Woofs.columns)).all()
    res = []
    for woof in woofs:
        # Schedule live refresh/backfill planning; do not block this API call.
        run_jobs(woof.id, -1, woof.url)
        res.append(
            {
                "woofId": woof.id,
                "url": woof.url,
                "name": woof.name,
                "latestSeqNo": woof.latest_seq_no,
                "columns": [
                    {"field": col.field, "name": col.name, "conversion": col.conversion}
                    for col in woof.columns
                ],
            }
        )
    return res


def delete_woof_from_db(id):
    woof = db_session.query(Woofs).filter(Woofs.id == id).first()
    if woof:
        db_session.delete(woof)
        db_session.commit()


################
# Users / state
################

def add_user_to_db(uname, pwd, isAdmin, roles=None):
    obj = None
    try:
        obj = get_user_from_db(uname)
        if not obj:
            obj = Users(
                username=uname,
                password=sha256_crypt.hash(pwd),
                isAdmin=isAdmin,
                roles=roles,
            )
            db_session.add(obj)
            db_session.commit()
        else:
            _log(f"add_user_to_db: user already in DB with ID: {obj.id}")
    except Exception as e:
        db_session.rollback()
        _log(f"Exception in add_user_to_db: {e}")
        traceback.print_exc()
    return obj


def add_users_in_list_to_db(ulist):
    for tpl in ulist:
        add_user_to_db(tpl[0], tpl[1], tpl[2])


def update_user_pwd(uname, pwd):
    try:
        obj = get_user_from_db(uname)
        if obj:
            obj.password = sha256_crypt.hash(pwd)
            db_session.commit()
            return True
        _log(f"update_user_pwd: user not found in DB: {uname}")
    except Exception as e:
        db_session.rollback()
        _log(f"Exception in update_user_pwd: {e}")
        traceback.print_exc()
    return False


def get_user_from_db(uname):
    return db_session.query(Users).filter(Users.username == uname).first()


def get_state(key):
    return db_session.query(State).filter(State.key == key).first()


def set_state(key, val):
    obj = db_session.query(State).filter(State.key == key).first()
    if obj:
        obj.val = val
    else:
        obj = State(key=key, val=val)
        db_session.add(obj)
    db_session.commit()


################
# Conversion helpers
################

def convert(val, conversion):
    try:
        floatval = float(val)
    except Exception as e:
        if DEBUG:
            _log(f"Exception in convert: {e}\n{val}, {conversion}")
        return val

    if conversion == "c2f":
        return f"{floatval * 1.8 + 32:.2f}"
    if conversion == "f2c":
        return f"{(floatval - 32) * 0.555:.2f}"
    if conversion == "mps2mph":
        return f"{floatval / 0.447:.2f}"
    if conversion == "mph2mps":
        return f"{floatval * 0.447:.2f}"
    if conversion == "kph2mph":
        return f"{floatval / 1.609:.2f}"
    if conversion == "mph2kph":
        return f"{floatval * 1.609:.2f}"
    if conversion == "mm2in":
        return f"{floatval / 25.4:.2f}"
    if conversion == "cm2in":
        return f"{floatval / 2.54:.2f}"
    if conversion == "mbar2hgby1000":
        return f"{floatval * 0.00002953:.2f}"
    return val


###############################
# Minimal test harness retained from the original utils.py.
###############################

def main():
    global DEBUG
    parser = argparse.ArgumentParser(
        description=(
            "Run utils.py tests/maintenance using a JSON config file. "
        )
    )
    parser.add_argument("args", action="store", help="json config file name specifying options")
    parsed = parser.parse_args()

    fname = parsed.args
    if not os.path.isfile(fname):
        print(f"Unable to open json file {fname}")
        sys.exit(1)

    try:
        with open(fname, "r") as jfile:
            args = json.load(jfile)
    except Exception as e:
        print(e)
        print("Unable to parse json file as expected")
        sys.exit(1)

    cleandb = args.get("cleandb", False)
    cleanworkers = args.get("cleanworkers", False)
    cleancols = args.get("cleancols", False)
    dumpwoofs = args.get("dumpwoofs", False)
    woofurls = args.get("woofurls", [])
    delete_urls = args.get("woofs_to_delete_completely", [])
    woofid = args.get("woofid")
    field = args.get("field", 0)
    start = args.get("start", -1)
    end = args.get("end", -1)
    agg = args.get("agg", None)
    intv = args.get("intv", "moment")
    runjobs = args.get("runjobs", False)
    DEBUG = args.get("DEBUG", DEBUG)

    print(f"TEST: cleaning db {cleandb}...")
    db.init_db(cleandb)

    if cleanworkers:
        print("TEST: cleaning queued jobs...")
        for q in {queue, live_q, dispatch_q, backfill_q}:
            try:
                q.empty()
            except Exception as e:
                print(f"Unable to empty queue {getattr(q, 'name', q)}: {e}")

    if cleancols:
        print("TEST: cleaning columns...")
        woofs = db_session.query(Woofs).all()
        for woof in woofs:
            woof.columns = []
        db_session.commit()

    print(f"TEST: delete woof {delete_urls}")
    for deleteurl in delete_urls:
        woof_to_delete = db_session.query(Woofs).filter(Woofs.url == deleteurl).first()
        if woof_to_delete:
            db_session.delete(woof_to_delete)
            db_session.commit()

    print(f"TEST: load_woof {woofurls}")
    woofmap = {}
    for woofurl in woofurls:
        wid = get_woof_id_from_url(woofurl)
        if wid is None:
            wid = get_woof_from_db(woofurl).id
        print(f"TEST: loadwoof {woofurl}: id={wid}")
        woofmap[woofurl] = wid
        val = load_woof(woofurl)
        print(f"TEST: loadwoof result={val}")

    if dumpwoofs:
        print("TEST: dumpwoofs")
        for woofurl in woofurls:
            print(f"TEST: dumpwoof {woofurl}")
            for row in get_all_woof_entries(woofurl):
                print(row)
            print()

    if start != -1 and woofid is not None:
        print("TEST: get_woof_values")
        res, _ = get_woof_values(woofid, field, start, end, agg, intv)
        for r in res:
            print(r)

    for woofurl in woofurls:
        wid = woofmap[woofurl]
        latest_seqno = get_latest_seqno_from_woofId(wid)
        earliest_seqno = get_earliest_seqno_from_woofId(wid)
        print(f"{woofurl}: min={earliest_seqno}, max={latest_seqno}")

    if runjobs:
        for woofurl in woofurls:
            print(f"running background jobs for {woofurl}")
            wid = woofmap[woofurl]
            run_jobs(wid, -1, woofurl)


if __name__ == "__main__":
    main()
