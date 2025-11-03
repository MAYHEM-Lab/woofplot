# db.py
'''
    Author: Chandra Krintz, 
    License: UCSB BSD -- see LICENSE file in this repository
'''
import traceback, sys, argparse, os, json, pytz, math
from datetime import datetime, timedelta, timezone
from passlib.hash import sha256_crypt
from sqlalchemy.sql import over
from sqlalchemy import UniqueConstraint, and_, func
from sqlalchemy.schema import DropTable
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import joinedload, Session

from db import db_session
from models import Users, Woofs, Columns, WoofData
import time, random
import db, cspot_utils, tasks
from redis import Redis
from redis_config import queue, redis_conn
MAX_WOOF_ELES = 10000 #typical number of entries in a woof
JOB_LIMIT = 200
SMALL_JOB = 20

tmp = os.environ.get("WPDEBUG")
if tmp.lower() in ['true', '1']:
    DEBUG = True
    print(f'turning on DEBUG mode!')
else: 
    DEBUG = False
secsmap = {
    "minute": 300,
    "hour": 3600,
    "day": 86400,
    "week": 604800,
    "moment": -1
}
PacTZ = pytz.timezone('US/Pacific')
DEDUP_TTL_SECONDS = 24 * 3600  # should exceed worst-case job runtime (24 hrs)

################
def find_missing_ranges(woof_id: int, start_seq: int):
    # window: previous seqno per woof, ordered by seqno
    prev_seq = func.lag(WoofData.seqno).over(
        partition_by=WoofData.woof_id,
        order_by=WoofData.seqno,
    )

    # subquery: only rows for this woof_id at/after start_seq
    subq = (
        db_session.query(
            WoofData.seqno.label("seqno"),
            prev_seq.label("prev_seq"),
        )
        .filter(
            and_(
                WoofData.woof_id == woof_id,
                WoofData.seqno >= start_seq,
            )
        )
        .subquery()
    )

    # internal gaps (where current seqno is more than 1 greater than previous)
    rows = (
        db_session.query(
            (subq.c.prev_seq + 1).label("gap_start"),
            (subq.c.seqno - 1).label("gap_end"),
        )
        .filter(
            subq.c.prev_seq.isnot(None),
            subq.c.seqno > subq.c.prev_seq + 1,
        )
        .order_by(subq.c.prev_seq)
        .all()
    )

    gaps = []

    # check if there's an initial gap from start_seq to the first actual seqno we have
    first_seq = (
        db_session.query(WoofData.seqno)
        .filter(
            and_(
                WoofData.woof_id == woof_id,
                WoofData.seqno >= start_seq,
            )
        )
        .order_by(WoofData.seqno)
        .limit(1)
        .scalar()
    )
    if first_seq is not None and first_seq > start_seq:
        gaps.append((start_seq, first_seq - 1))

    # add the internal gaps
    gaps.extend((int(a), int(b)) for a, b in rows)

    return gaps

################
def split_ranges(ranges, max_span: int):
    out = []
    for a, b in ranges:
        x = a
        while x <= b:
            y = min(x + max_span - 1, b)
            out.append((x, y))
            x = y + 1
    return out

################
def split_ranges_desc(ranges, max_span: int):
    out = []
    for a, b in ranges:
        # walk this gap from high → low
        x = b
        while x >= a:
            y = max(a, x - max_span + 1)
            out.append((y, x))
            x = y - 1
    return out

################
def enqueue_woof_load_jobs(woof_id: int, woofurl: str, cspot_seqno: int, *, chunk_size: int = JOB_LIMIT):
    startsn = cspot_seqno - 9000 #assuming a 10K buffer for most
    if startsn < 10:
        startsn = 10
    gaps = find_missing_ranges(woof_id,startsn)
    #process more recent gaps first
    gaps.sort(key=lambda r: r[1], reverse=True)
    jobs = split_ranges_desc(gaps, chunk_size)

    enqueued = 0
    for start, end in jobs:
        count = end - start + 1
        dedupe_key = f"woofload:dedupe:{woof_id}:{start}:{count}"
        # Reserve atomically; skip if already reserved/enqueued/running recently
        if not redis_conn.set(dedupe_key, "1", nx=True, ex=DEDUP_TTL_SECONDS):
            continue

        # Let RQ assign a fresh job_id so we can immediately re-enqueue later
        try:
            queue.enqueue(
                tasks.woof_load_task,
                args=(woofurl, start, count),
                kwargs={"woof_id": woof_id},
                result_ttl=3600,
                failure_ttl=86400,
            )
            enqueued += 1
        except Exception:
            # If enqueue fails, release reservation so it can be retried
            print(f"Enqueue failure woof_id={woof_id}",flush=True)
            redis_conn.delete(dedupe_key)
            raise

    if DEBUG:
        print(f"Enqueued {enqueued} jobs for woof_id={woof_id}",flush=True)
    return enqueued

################
def decimate(lst, target_count):
    # Calculate the step size based on the target count
    step = max(1, len(lst) // target_count)  # Ensure step is at least 1
    return lst[::step]

################
def get_woof_values(woofId,field,s,e,agg,interval,raw=None): #between millisecond timestamps s and e
    # called by routes.py /api/query/ GET
    start = s/1000 #convert the millisecond values to seconds
    startdt = datetime.fromtimestamp(start,tz=PacTZ)
    end = e/1000
    enddt = datetime.fromtimestamp(end,tz=PacTZ)
    timediff = end-start
    div = secsmap[interval]
    if raw:
        assert interval == 'moment'
        count_to_return = int(raw)
    else:
        count_to_return = int(timediff/div)
    #count_to_return is the resulting decimated count, DB will likely return more

    woofvals = []
    responses = []
    if DEBUG:
        print(f'get_woof_values: {woofId}, {field}, {s}:{start}:{startdt}')
        print(f'\t{agg}, {interval}, {e}:{end}:{enddt}, {raw}')
        print(f'\tcount to return: {count_to_return}',flush=True)
    try:
        wurl = get_woof_url_from_id(woofId)
        #err = load_woof(wurl) #load the 20 most recent (if delay is too long, change limit)
        #assert err is not None

        # now get the results from the db and decimate them randomly to return only 
        # the count_to_return if there are fewer rows it will return all of them
        #attributes: id, ts, seqno, data
        rand_rows = db_session.query(WoofData).filter(  
            and_(
                WoofData.woof_id == woofId,  # Filter by woof_id
                WoofData.ts >= startdt,    
                WoofData.ts <= enddt
            ) #).order_by(func.random()).limit(count_to_return).all()
        ).order_by(WoofData.ts).all()
        retn_len = len(rand_rows) 
        if retn_len == 0:
            #no results
            if DEBUG:
                print(f'\treturning from get_woof_values -- no results found',flush=True)
            retn = {f"WOOFPLOT": f"get_woof_values nothing returned for woof {woofId}: {start}:{startdt}, {end}:{enddt}"}
            return [],200
        first_woof_ts = rand_rows[0].ts
        first_woof_seqno = rand_rows[0].seqno
        last_woof_seqno = rand_rows[-1].seqno
        tdiff = first_woof_ts - startdt
        if DEBUG:
            print(f"\tquery startdt: {startdt} and enddt: {enddt} -- count_to_return: {count_to_return} -- timediff: {tdiff} {tdiff.total_seconds()/60}",flush=True)
            print(f"\tquery ts returned: {rand_rows[0].ts} -- {rand_rows[retn_len-1].ts}, eles: {retn_len} tdiff: {tdiff.days}",flush=True) 

        #keep the first and last from rand_rows
        results = []
        results.append(rand_rows[0])
        dec_val = os.environ.get("DECIMATE_SKIP")
        if dec_val is not None:
            dec_val = int(dec_val)
        else:
            dec_val = 250
        if retn_len > dec_val:
            if DEBUG:
                print(f"\tDECIMATING... using val {dec_val}",flush=True)
            templist = decimate(rand_rows[1:-1], count_to_return)
        else: 
            templist = rand_rows[1:-1]
        results.extend(templist)
        results.append(rand_rows[-1])

        #process results for returning
        if DEBUG:
            print(f"\tprocessing results {len(results)}",flush=True)
        TYP = None
        for result in results:
            response = {}  #woofId, field, ts, val
            response['woofId'] = woofId
            response['field'] = field
            conv = get_conversion(woofId,field)
            val = ""
            TYP = 'string'
            try:
                val = float(result.data)
                TYP = 'float'
            except ValueError as e: #its a colon-delimited string so parse it:
                tmpv = result.data.split(':')
                assert len(tmpv) > field
                val = tmpv[field]
            epoch = result.ts.timestamp()
            ts = int(epoch * 1000) #fend expects millis
            response['timestamp'] = ts
            #convert the value here if needed
            if conv and conv != "No conversion":
                val = convert(val,conv)
            response['value'] = val
            responses.append(response)

        if DEBUG:
            print(f"RETURNING: getting entry for woofId {woofId}: {len(responses)} responses",flush=True)

    except Exception as e:
        print(f"Exception in get_woof_values: {e}",flush=True)
        traceback.print_exc()
        retn = {f"WOOFPLOT": "get_woof_values exception {e}"}
        return retn,500
        
    return responses, 200
    
################
def cspot_get(url,seqno=-1):
    FAILED = True
    exc = val = None
    try:
        val = cspot_utils.senspot_get(url,seqno=seqno)[0]
        if val != b'':
            FAILED = False 
    except Exception as e:
        exc = e
    if FAILED:
        msg = {"WOOFPLOT": f"cspot_get senspot_get failed {exc}"}
        return msg,False
    res = val.decode('utf-8').strip().split(' ')
    return res,True

################
def add_or_update_woof_in_db(data,seqno = -1): 
    #called by routes:/api/woof [POST,PUT]
    #data contains keys: url, name, columns[field,name,conversion] --> to add a woof without columns pass in columns as [], the rest is required but name gets updated if it changes
    woofurl = data["url"]
    woof = None
    try:
        woof = get_woof_from_db(woofurl) 
        if not woof:  #create woof and columns
            #a new woof better not have a seqno with value -1 as a cspot_get 
            #should have been called to pass an actual value in and set it!
            assert seqno != -1
            woof = add_woof_to_db(woofurl) 
            woof.name = data["name"]
            woof.latest_seq_no = data["seqno"]
            for col in data["columns"]:
                column = Columns(
                    field = col["field"],
                    name = col["name"],
                    conversion = col["conversion"],
                    woof=woof #automatically associates column to woof
                )
            db_session.add(woof)
        else: 
            #update the name if different (url is unique but name can change and we can reuse the data)
            woof.name = data["name"]
            #update the current_columns to match the ones passed in for the woof
            current_columns = woof.columns
            client_field_list = [] #list of fields sent by client
            #process the columns sent by the client and add missing ones
            for client_col in data["columns"]:
                client_field_list.append(client_col["field"])
                id2check = client_col["field"]
                Done = False
                for curr in current_columns:
                    if curr.field == id2check: #update vals in case they changed
                        curr.name = client_col["name"]
                        curr.conversion = client_col["conversion"]
                        Done = True #found it so skip to next one
                    if Done: 
                        break
                if not Done: #add it
                    column = Columns(
                        field = client_col["field"],
                        name = client_col["name"],
                        conversion = client_col["conversion"],
                        woof=woof 
                    )
                    db_session.add(column)
            #process the columns for this woof in db, remove any not sent by client
            if client_field_list != []:
                for curr in current_columns:
                    field = curr.field
                    if field not in client_field_list:
                        column_to_delete = db_session.query(Columns).filter(Columns.field == field, Columns.woof_id == woof.id).first()
                        db_session.delete(column_to_delete)

        db_session.commit()
    except Exception as e:
        print(f"Exception in add_or_update_woof_in_db: {e}",flush=True)
        traceback.print_exc()
    return woof

################
def add_user_to_db(uname,pwd,isAdmin,roles=None): 
    obj = None
    try:
        obj = get_user_from_db(uname) 
        if not obj: #if not exists
            pwdhash = sha256_crypt.hash(pwd)
            obj = Users(
                username = uname,
                password = pwdhash,
                isAdmin = isAdmin,
                roles = roles
            )
            db_session.add(obj)
            db_session.commit()
        else:
            print("add_user_to_db: user already in DB with ID: {}".format(obj.id))
    except Exception as e:
        print(f"Exception in add_user_to_db: {e}", flush=True)
        traceback.print_exc()
    return obj

################
def update_user_pwd(uname,pwd): 
    obj = None
    try:
        obj = get_user_from_db(uname) 
        if obj: #if not exists
            pwdhash = sha256_crypt.hash(pwd)
            obj.password = pwdhash
            db_session.commit()
            return True
        else:
            print(f"update_user_pwd: user not found in DB: {unane}")
    except Exception as e:
        print(f"Exception in update_user_pwd: {e}", flush=True)
        traceback.print_exc()
    return False

################
def get_user_from_db(uname):
    return db_session.query(Users).filter(Users.username == uname).first()

################
def get_woof_from_db(url):
    woof = db_session.query(Woofs).filter(Woofs.url == url).first()
    if not woof:
        woof = add_woof_to_db(url) 
    return woof

################
def get_latest_seqno_from_woofId(id):
    retn = db_session.query(Woofs).with_entities(Woofs.latest_seq_no).filter(Woofs.id == id).first()
    if retn:
        return retn[0]
    return None

################
def get_earliest_seqno_from_woofId(woof_id):
    min_seq = (
        db_session.query(func.min(WoofData.seqno))
        .filter(WoofData.woof_id == woof_id)
        .scalar()
    ) or -1
    return min_seq

################
def get_woof_url_from_id(id):
    retn =  db_session.query(Woofs).with_entities(Woofs.url).filter(Woofs.id == id).first()
    if retn:
        return retn[0]
    return None

################
def get_woof_id_from_url(url):
    retn =  db_session.query(Woofs).with_entities(Woofs.id).filter(Woofs.url == url).first()
    if retn:
        return retn[0]
    return None

################
def get_woof_entry(woofId, seqno=-1):
    if seqno == -1:
        seqno = get_latest_seqno_from_woofId(woofId)
    return db_session.query(WoofData).filter(WoofData.woof_id == woofId, WoofData.seqno == seqno).first()

################
def get_conversion(woofId, field):
    retn = db_session.query(Columns).filter_by(woof_id=woofId, field=field).first()
    if retn:
        return retn.conversion
    return None

################
def convert(val, conversion):
    try:
        floatval = float(val)
    except Exception as e:
        if DEBUG:
            print(f"Exception in convert: {e}\n{val}, {conversion}",flush=True)
        return val
    if conversion == "c2f":
        f = floatval*1.8 + 32
        val = f"{f:.2f}"
    elif conversion == "f2c":
        c = (floatval - 32)*0.555
        val = f"{c:.2f}"
    elif conversion == "mps2mph":
        mph = floatval / 0.447
        val = f"{mph:.2f}"
    elif conversion == "mph2mps":
        mps = floatval * 0.447
        val = f"{mps:.2f}"
    elif conversion == "kph2mph":
        mph = floatval / 1.609
        val = f"{mph:.2f}"
    elif conversion == "mph2kph":
        kph = floatval * 1.609
        val = f"{kph:.2f}"
    return val

################
def get_all_woof_entries(woofurl):
    woof = get_woof_from_db(woofurl)
    if DEBUG:
        print(f"get_all_woof_entries {woof}",flush=True)
    return woof.woofdata

################
def get_state(key):
    return db_session.query(State).filter(State.key == key).first()

################
def set_state(key,val):
    obj = db_session.query(State).filter(State.key == key).first()
    if obj:
        obj.val = val
    else:
        obj = State(
            key = key,
            val = val
        )
        db_session.add(obj)
    db_session.commit()

################
def add_woof_to_db(woofurl):
    woof = Woofs(
        url = woofurl,
        name = "woofname",
        latest_seq_no = -1
    )
    db_session.add(woof)
    db_session.commit
    return woof

################
def delete_woof_from_db(id):
    #instead of actually deleting the woof, delete the columns for the woof
    #this will cause the frontend to not display the woof as available but won't delete the data
    #woofdata is deleted as part of the retention policy or manually
    woof = db_session.query(Woofs).filter(Woofs.id == id).first()
    woof.columns = []  #this will cause all of the Columns to be deleted because of the cascade option in Woofs for columns attribute
    db_session.commit()

################
def get_all_woofs_from_db():
    # get and return all woofs in a datastructure that will be passed back to frontend 

    # Query all Woof objects along with their associated Columns using eager loading
    woofs = db_session.query(Woofs).options(joinedload(Woofs.columns)).all()

    # Create a list of dictionaries to represent the result
    res = []
    for woof in woofs:
        #spawn job in background to load a small number of latest entries for each woof to prime the pump
        run_jobs(woof.id,-1)
        woof_data = {
            'woofId': woof.id,
            'url': woof.url,
            'name': woof.name,
            'latestSeqNo': woof.latest_seq_no,
            'columns': [
                {
                    'field': column.field,
                    'name': column.name,
                    'conversion': column.conversion
                } for column in woof.columns
            ]
        }
        res.append(woof_data)
    return res

################
def add_users_in_list_to_db(ulist):
    for tpl in ulist:
        add_user_to_db(tpl[0],tpl[1],tpl[2])

################
def call_run_jobs(woofurl,limit=JOB_LIMIT):
    wid = get_woof_id_from_url(woofurl)
    run_jobs(wid,limit,woofurl)

################
def run_jobs(woofId,limit=JOB_LIMIT,wurl=None):
    # run background job to load woof entries ahead of the earliest sequence number
    # called by get_woof_values (routes.py /api/query/ GET), get_all_woofs_from_db (routes.py:/api/woof/ GET)
    try:
        woofurl = wurl
        if wurl == None:
            woofurl = get_woof_url_from_id(woofId)
        if DEBUG:
            print(f"run_jobs: setting up background job for {woofurl} {woofId}, limit: {limit}",flush=True)
        if limit == -1: #just call load_woof which loads a small number of the most recent entries
            #create a unique job ID so that we don't keep running this if we've already enqueued it
            latest = None
            res,OK = cspot_get(woofurl)
            if  OK:
                latest = int(res[5])
            dedupe_key = f"woofload:dedupe:{woofId}:{latest}:{SMALL_JOB}"
            #returns True if we get the reservation and should enqueue (else None)
            v = redis_conn.set(dedupe_key, "1", nx=True, ex=DEDUP_TTL_SECONDS)
            if DEBUG:
                print(f"run_jobs2: {woofurl} {woofId}, limit: {limit} latest: {latest}",flush=True)
                print(f"\tdedupe_key: {dedupe_key}")
            # Reserve atomically; skip if already reserved/enqueued/running recently
            if v == True:
                try:
                    queue.enqueue(tasks.woof_load_task, 
                        args=(woofurl, -1, SMALL_JOB), 
                        kwargs={"woof_id": woofId, "latest": latest},
                    )
                    #calls load_woof(woofurl,-1,SMALL_JOB)
                except Exception:
                    # If enqueue fails, release reservation so it can be retried
                    print(f"Enqueue0 failure woof_id={woof_id}",flush=True)
                    redis_conn.delete(dedupe_key)
                    raise

            if latest:
                #now create more jobs that fill in the holes in the DB
                enqueue_woof_load_jobs(woofId, woofurl, latest)

        else:
            if DEBUG:
                print(f"run_jobs3: {woofurl} {woofId}, limit: {limit}",flush=True)
            earliest_seqno = get_earliest_seqno_from_woofId(woofId) #esno in database
            assert earliest_seqno != -1  #this should never happen
            #handle case where we are near the start of a woof
            # if earliest - limit is negative, then don't load anything (we are at/near start)
            startsno = earliest_seqno - limit
            if startsno > 10: #make the load worth our while (we load at least 10 entries)
                if limit > JOB_LIMIT:
                    lim = limit
                    while lim > 0: #run multiple jobs with different startsnos
                        dedupe_key = f"woofload:dedupe:{woofId}:{startsno}:{JOB_LIMIT}"
                        if DEBUG:
                            print(f"\tdedupe_key: {dedupe_key}")
                        # Reserve atomically; skip if already reserved/enqueued/running recently
                        if redis_conn.set(dedupe_key, "1", nx=True, ex=DEDUP_TTL_SECONDS):
                            try:
                                queue.enqueue(tasks.woof_load_task, 
                                    args=(woofurl, startsno, JOB_LIMIT), 
                                    kwargs={"woof_id": woofId},
                                )
                                #calls load_woof(woofurl,startsno,JOB_LIMIT)
                            except Exception:
                                # If enqueue fails, release reservation so it can be retried
                                print(f"Enqueue1 failure woof_id={woof_id}",flush=True)
                                redis_conn.delete(dedupe_key)
                                raise
                        startsno = startsno - JOB_LIMIT
                        if startsno < 10: #nearing the first element in the woof, don't bother loading
                            break
                        lim = lim - JOB_LIMIT
                else:
                    dedupe_key = f"woofload:dedupe:{woofId}:{startsno}:{limit}"
                    if DEBUG:
                        print(f"\tdedupe_key: {dedupe_key}")
                    # Reserve atomically; skip if already reserved/enqueued/running recently
                    if redis_conn.set(dedupe_key, "1", nx=True, ex=DEDUP_TTL_SECONDS):
                        try:
                            queue.enqueue(tasks.woof_load_task, 
                                args=(woofurl, startsno, limit), 
                                kwargs={"woof_id": woofId},
                            )
                            #calls load_woof(woofurl,startsno,limit)
                        except Exception:
                            # If enqueue fails, release reservation so it can be retried
                            print(f"Enqueue2 failure woof_id={woof_id}",flush=True)
                            redis_conn.delete(dedupe_key)
                            raise
            else:
                print(f"WARNING: Not loading from start of woof for {woof_id}:{startsno}:{limit}",flush=True)
    except Exception as e:
        print(f"Exception in run_jobs: {e}",flush=True)

################
def load_woof(woofurl,endsn=-1,count=SMALL_JOB): # limit the number loaded (count) to prevent bg job death/delays
    # Call senspot_get and put the data in the DB
    # Do this for cspot seqnos between startsn and endsn-1 inclusively (or latest if endsn=-1)
    # Returns the cspot return associated with the largest seqno retreived (latest if endsn=-1) or None on err
    # Called by: utils.py:run_jobs(woofId,count_to_return,wurl) --> queue.enqueue(...)
    # Called by: tasks.py as a background job

    #Cases:
    #   new woof (only pass in url), add count eles ending in the latest_seqno, add this seqno to the woof
    #   existing woof (only pass in url), add eles from DB end/latest up to the latest_seq_no recorded in the woof
    #   seqno range 

    # CJK problem
    #load_woof: woof://169.231.230.76/sharedfs/unl-data/daviscupsout, 1, 21: 8322
        #load_woof problem: woofid: 3 startsn -20 endsn 1
    woof = get_woof_from_db(woofurl) #adds it if not there
    latest = woof.latest_seq_no
    print(f"load_woof: {woofurl}, {endsn}, {count}: {latest}")
    #load_woof: woof://169.231.230.76/sharedfs/unl-data/daviscupsout, 1, 250: 234
    #     load_woof problem: woofid: 6 startsn -249 endsn 1
    retn = None #return the ts, seqno, data for last cspot entry loaded
    if endsn == -1: #get the woof latest and work back
        res,OK = cspot_get(woofurl)
        if not OK:
            print(f'load_woof [latest]: cspot call failed {woofurl} trying again...')
            time.sleep(0.5)
            res,OK = cspot_get(woofurl)  #res format (indices: val/data=0, ts=2, seqno=5)
            #472.000000 time: 1732476793.9533109665 10.0.1.158 seq_no: 76147
            #val1:val2 time: 1732476793.9533109665 10.0.1.158 seq_no: 76147
            if not OK:
                print(f'load_woof [latest]: 2nd try cspot call failed {woofurl} failed')
                print(f"WOOFPLOT: latest load_woof error: cspot call failed")
                return None

        #set startsn and endsn for loading range
        endsn = int(res[5])
        if latest == -1: #new woof, just back up count and load it to wooflatest
            startsn = int(endsn - count)
        else: #existing woof, load from db latest to wooflatest
            startsn = int(latest)

        woof.latest_seq_no = endsn #update the database to match wooflatest which we are about to add
        db_session.commit() #commit right away in case there is a race to add data for some reason
        epoch = float(res[2])
        ts = datetime.fromtimestamp(epoch)
        retn = (ts,endsn,res[0]) #return the latest
        if endsn == startsn:
            if DEBUG: 
                print(f"\tload_woof: returning the latest {retn}",flush=True)
            return retn #ts, seqno, data for the last entry in the DB

        #add the latest woof to the db, its not there if we reached here
        if DEBUG:
            print(f'adding latest woofdata {ts}:{endsn}:{res[0]}',flush=True)
        woofdata = WoofData(
            ts = ts,
            seqno = endsn,
            data = res[0].strip(),
            woof=woof 
        )
        db_session.add(woofdata)
        db_session.commit()

    else: #valid endsn was passed in, get the startsn, load seqno range (startsn to endsn)
        assert latest != -1 #sanity check that this isn't a new woof, this is latest_seqno in DB
        startsn = int(endsn-count)
    if startsn <= 0: 
        print(f"\tload_woof problem: woofid: {woof.id} startsn {startsn} endsn {endsn}, count: {count}",flush=True)  #we could just return None at this point...
        #assert False #assert startsn > 0
        return None

    #load the missing data into the database from the woof
    print(f"\tload_woof: loading missing data from startsn {startsn} to endsn {endsn}",flush=True)
    for seqno in range(startsn, endsn):
        #check if its already in the db, and skip if so
        ts_exists = db_session.query(WoofData).filter(WoofData.seqno == seqno, WoofData.woof_id == woof.id).first()
        if ts_exists:
            if seqno == endsn-1: #save off the last one
                retn = (ts_exists.ts,seqno,ts_exists.data) 
            continue
        #get the cspot value for this seqno
        res,OK = cspot_get(woofurl,seqno)
        if not OK:
            print(f'load_woof: cspot call failed {woofurl} {seqno} trying again...')
            time.sleep(0.5)
            res,OK = cspot_get(woofurl,seqno)  #res format (indices: val=0, ts=2, seqno=5)
            #472.000000 time: 1732476793.9533109665 10.0.1.158 seq_no: 76147
            #val1:val2 time: 1732476793.9533109665 10.0.1.158 seq_no: 76147
            if not OK:
                print(f'load_woof: 2nd try cspot call failed {woofurl} {seqno} failed')
                print(f"WOOFPLOT: load_woof error2: cspot call failed")
                return None
        epoch = float(res[2])
        ts = datetime.fromtimestamp(epoch)
        woofdata = WoofData(
            ts = ts,
            seqno = seqno,
            data = res[0].strip(),
            woof=woof 
        )
        db_session.add(woofdata)
        db_session.commit()
        if seqno == endsn-1: #save off the last one
            retn = (ts,seqno,res[0]) 
        
    print(f"\tload_woof: done with woof {woofurl}")
    return retn #ts, seqno, data for the last entry in the DB (only used for debugging)

###############################
def main():
    global DEBUG
    parser = argparse.ArgumentParser(description='Running this file directly either cleans out the DB (-c flag) or checks that the DB is setup and ready to go for woofplot (no args). The program should exit without errors.')
    parser.add_argument('args',action='store',help='json config file name specifying the options')
    args = parser.parse_args()

    fname = args.args
    if not os.path.isfile(fname):
        print(f"Unable to open json file {fname}")
        sys.exit(1)
    try:
        with open(args.args, "r") as jfile:
            args = json.load(jfile)
        cleandb = args["cleandb"]
        cleanworkers = args["cleanworkers"]
        cleancols = args["cleancols"]
        dumpwoofs = args["dumpwoofs"]
        woofurls = args["woofurls"] #list
        delete_urls = args["woofs_to_delete_completely"] #list
        woofid = args["woofid"]
        field = args["field"]
        start = args["start"] #set to -1 to skip get_woof_values test
        end = args["end"]
        agg = args["agg"]
        intv = args["intv"]
        runjobs = args["runjobs"]
        DEBUG = args["DEBUG"]
    except Exception as e:
        print(e)
        print("Unable to parse json file as expected")
        sys.exit(1)

    #same as python db.py [-c]
    #set cleandb to True to clean out DB, else just validates schemas
    print(f"TEST: cleaning db {cleandb}...")
    db.init_db(cleandb)

    if cleanworkers: 
        print(f"TEST: cleaning workers...")
        redis_conn = Redis()
        redis_conn.delete('rq:failed:default')
        for job in queue.jobs: 
            job.cancel() 

    if cleancols: #set all woofs in db to have cols sent to empty list (deleting the columns)
        print(f"TEST: cleaning columns...")
        #this causes the frontend not to see any fields to plot in the pull down list
        woofs = db_session.query(Woofs).all()
        for woof in woofs:
            woof.columns = []
        db_session.commit()
        
    print(f"TEST: delete woof {delete_urls}")
    for deleteurl in delete_urls: #careful! this will delete columns and woofdata!! 
        woof_to_delete = db_session.query(Woofs).filter(Woofs.url == deleteurl).first()
        if woof_to_delete:
            db_session.delete(woof_to_delete)
            db_session.commit()
    
    ############## TESTS ##################
    # load woofs, if woof doesn't exist, add it
    # no seqno passed in, says get latest back to latest if there is one, 
    #else create woof and load to limit
    print(f"TEST: load_woof {woofurls}")
    latest = latestwoofurl = None
    woofmap = {}
    for woofurl in woofurls:
        wid = get_woof_id_from_url(woofurl)
        print(f"TEST: loadwoof {woofurl}: id={wid}")
        woofmap[woofurl] = wid
        val = load_woof(woofurl) #returns (ts, seqno, data)
        assert val is not None

    if dumpwoofs:
        print(f"TEST: dumpwoofs")
        for woofurl in woofurls:
            print(f"TEST: dumpwoof {woofurl}")
            woofdata = get_all_woof_entries(woofurl)
            for woof in woofdata:
                print(f"{woof}")
            print()

    #get values between range - start/end in millisecond epochs (*1000)
    if start != -1:
        print(f"TEST: get_woof_values")
        res,_ = get_woof_values(woofid,field,start,end,agg,intv)
        for r in res:
            print(f"{r}")

    for woofurl in woofurls:
        wid = woofmap[woofurl]
        latest_seqno = get_latest_seqno_from_woofId(wid)
        earliest_seqno = get_earliest_seqno_from_woofId(wid)
        assert earliest_seqno != -1
        print(f"min: {earliest_seqno}, max: {latest_seqno}")

    if runjobs: 
        for woofurl in woofurls:
            print(f"running background jobs for {woofurl}")
            wid = woofmap[woofurl]
            run_jobs(wid)

###############################
if __name__ == "__main__":
    main()

