# fill_holes_from_woofdb.py
'''
    Author: Chandra Krintz, 
    License: UCSB BSD -- see LICENSE file in this repository
'''
import os, sys, dotenv, argparse, random, math, json, time
from datetime import datetime, timedelta

#import the db interface in the sensor_data_tools directory
sys.path.append(os.path.join(os.path.dirname(__file__), '../sensor_data_tools', 'DB'))
import dbiface

from math import ceil
from sqlalchemy import create_engine
from sqlalchemy.sql import func, and_
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.orm import load_only
from sqlalchemy.dialects.postgresql import insert as pg_insert
from contextlib import contextmanager
from sqlalchemy import func, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert
from psycopg2.extras import execute_values

dotenv.load_dotenv()
tmp = os.environ.get("WPDEBUG")
if tmp.lower() in ['true', '1']:
    DEBUG = True
else: 
    DEBUG = False
dburi = os.environ.get("SQLALCHEMY_DATABASE_URI")
dbname = os.environ.get("DATABASE")
engine = create_engine(dburi)
db_session = scoped_session(sessionmaker(
    autocommit=False, autoflush=False, bind=engine))

#set seed on DB's random function
seed_value = float(os.environ.get("INTEGER_SEED_VALUE"))
scaled_value = math.tanh(seed_value) #convert it to value between -1 and 1
db_session.execute(func.setseed(scaled_value))

#Everything below happens after the db_session is created, thus can use the db
import utils
from models import Base, Woofs, WoofData

#woofdb db
db = None

######################################

CHUNK_SIZE  = 5_000   # seqno window; tune down if rows are big
SUB_BATCH   = 1_000   # rows per INSERT ... VALUES (...),(...)

@contextmanager
def new_session_like(db_session):
    """Create a short-lived session bound to the same engine as db_session."""
    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine, future=True)
    s = Session()
    try:
        yield s
    finally:
        s.close()

def batched(iterable, n):
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= n:
            yield batch
            batch = []
    if batch:
        yield batch

def process_woof(db_session, woof, tname, DEBUG=False):
    # NOTE: these queries open a transaction on db_session; we'll end it right after.
    startsno = db_session.query(func.min(WoofData.seqno)).filter(WoofData.woof_id == woof.id).scalar()
    endsno   = db_session.query(func.max(WoofData.seqno)).filter(WoofData.woof_id == woof.id).scalar()

    if startsno is None or endsno is None:
        if DEBUG:
            print(f'No data to process for {woof.url}')
        return

    if DEBUG:
        print(f'processing {woof.url} startseqno: {startsno} endseqno: {endsno}', flush=True)

    # End the read txn before starting our write windows
    db_session.commit()

    total_chunks = ceil((endsno - startsno + 1) / CHUNK_SIZE)

    # Prepared INSERT with ON CONFLICT; we’ll feed values via psycopg2.execute_values
    # (This path avoids creating ORM instances and minimizes Python overhead.)
    insert_sql = """
        INSERT INTO woofdata (seqno, ts, data, woof_id)
        VALUES %s
        ON CONFLICT (woof_id, ts) DO NOTHING
    """

    for idx, chunk_start in enumerate(range(startsno, endsno + 1, CHUNK_SIZE), start=1):
        chunk_end = min(chunk_start + CHUNK_SIZE - 1, endsno)
        if DEBUG:
            print(f'[{idx}/{total_chunks}] seqno chunk: {chunk_start}–{chunk_end}', flush=True)

        # IMPORTANT: make sure get_woofdb_data returns an *iterator/generator* (not a giant list).
        # If it currently returns a list, you can still iterate and sub-batch below, but consider
        # changing it to yield rows to reduce peak memory.
        rows_iter = get_woofdb_data(tname, chunk_start, chunk_end)  # yields (seqno, ts, data)

        # Use a short-lived session/connection per window to keep memory flat.
        with new_session_like(db_session) as s:
            # Raw psycopg2 connection underneath SQLAlchemy connection
            conn = s.connection().connection
            with conn.cursor() as cur:
                inserted = 0
                for sub in batched(rows_iter, SUB_BATCH):
                    # Transform to sequence of tuples matching VALUES %s
                    values = [(seq, ts, data, woof.id) for (seq, ts, data) in sub]
                    if not values:
                        continue
                    # execute_values constructs a single INSERT ... VALUES (...),(...),... statement
                    # which is both fast and memory-friendly for medium batches
                    execute_values(cur, insert_sql, values, page_size=len(values))
                    inserted += len(values)
                conn.commit()

        if DEBUG:
            print(f'   committed chunk {chunk_start}–{chunk_end}', flush=True)

    if DEBUG:
        print('Done.', flush=True)

######################################
def get_wweather(startsno,endsno): #returns list of entries to write
    cur = db.get_cursor()
    cur.execute(f"select * from wweather where seqno >= {startsno} and seqno < {endsno} order by seqno")
    rows = cur.fetchall()
    retn = []
    for row in rows:
        #seqno, dt, temp...windgust (9)
        retn.append((row[0],row[1],':'.join(str(x) for x in row[2:])))
    return retn

######################################
def get_wu(tname,startsno,endsno): #returns list of entries to write
    cur = db.get_cursor()
    cur.execute(f"select * from {tname} where seqno >= {startsno} and seqno < {endsno} order by seqno")
    rows = cur.fetchall()
    retn = []
    for row in rows:
        #row = (296700.0, datetime.datetime(2025, 9, 30, 18, 50, 2, 879616), '172.31.19.53', '29.96:9:16:248:69:95:0.0:0.0:69:66:69:1:2025-09-30_18-50-00')
        
        '''
        #seqno, dt, ip, info, baro...dtmeas (13), epoch
        third = ':'.join(str(x) for x in row[4:-3])
        #update 2nd-to-last entry from 2024-03-19 05:34:09-07:00 to 2025-04-09_14-39-59
        dt = row[-2]
        if DEBUG:
            print(f'{row}\n\t{dt}, {third}')
        formatted = dt.strftime('%Y-%m-%d_%H-%M-%S')
        third = f'{third}:{formatted}'
        '''
        retn.append((row[0],row[1],row[3]))
    return retn

######################################
def get_woofdb_data(tname,startsno,endsno): #returns list of entries to write
    #of the form: ts, seqno, data (colon delimited data)
    if tname == 'wweather':
        return get_wweather(startsno, endsno)
    elif tname.startswith('wu_'):
        return get_wu(tname,startsno, endsno)
    else:
        cur = db.get_cursor()
        #seqno, dt, data --> data could be a scalar float (fluxco2) or colon-delimited string (wise_soil3)
        cur.execute(f"select seqno,dt,data from {tname} where seqno >= {startsno} and seqno < {endsno} order by seqno")
        rows = cur.fetchall()
        return rows

######################################
def get_tname(woofurl): #returns table name used in woofdb
    woof = woofurl.strip()
    slashindex = woof.rfind('/')
    if slashindex == -1:
        tname = woof.replace('-','_').replace('.','_').lower()
    else:
        assert slashindex < len(woof) #sanity check
        tname = woof[slashindex+1:].replace('-','_').replace('.','_').lower() #from last index to end
    #update table names as woofs get reset this must match alerts/checkDBtables.py
    if tname == 'wu_30':
        tname = 'wu_30_new'
    if tname == 'wu_31':
        tname = 'wu_31_new'
    if tname == 'wu_32':
        tname = 'wu_32_new'
    if tname == 'elecdata_home':
        tname = 'elecdata_home2'
    if tname == 'goleta_home_data':
        tname = 'goleta_home_data2'
    if tname == 'goleta_home_data_rain_rate':
        tname = 'goleta_home_data_rain_rate2'
    if tname == 'goleta_home_data_rain_day':
        tname = 'goleta_home_data_rain_day2'
    return tname


###########################
def main():
    ''' 
    python fill_holes_from_woofdb.py args.json #see the json file for argument details
    This program fills in entries into the woofplot tables for missing seqnos from the woofdb on the alerts system.  It gets the earliest sequence number from woofplot for each woof.id and works forward, looking for holes.  It fills in the holes from woofdb. If you want to add data ahead of the earliest sequence number, use update_db_from_woofdb.py instead.
    '''
    global DEBUG, db
    parser = argparse.ArgumentParser(description='update woofplot table data from woofdb')
    parser.add_argument('json',action='store',help='json file holding the program args, see args file for details')
    pargs = parser.parse_args()

    if not os.path.isfile(pargs.json):
        print("Unable to open json file {}. \nUSAGE: python fill_holes_from_woofdb.py cf.json".format(pargs.json))
        sys.exit(1)
    try:
        with open(pargs.json, "r") as jfile:
            args = json.load(jfile)
        woofdbhost = args["dbinfo"]["host"]
        woofdb = args["dbinfo"]["db"] 
        woofdbpwd = args["dbinfo"]["pwd"] 
        woofdbuser = args["dbinfo"]["user"] 
        if not DEBUG: #set either via .env or json config file
            DEBUG = args["DEBUG"]
    except Exception as e:
        print(e)
        print("Unable to parse json file as expected. \nUSAGE: python3 fill_holes_from_woofdb.py cf.json")
        sys.exit(1)

    print(f'Debug flag: {DEBUG}')
    #db is the woofdb from which we are loading
    db = dbiface.DBobj(woofdb,woofdbpwd,woofdbhost,woofdbuser)

    #db_sessionis the woofplot database
    woofs = db_session.query(Woofs).all()
    for woof in woofs:
        tname = get_tname(woof.url)
        print(f'processing woof: {woof.id}\n\t{woof.url} and tname: {tname}')
        #assert db.table_exists(tname) #ensure that the table exists in the woofdb
        if not db.table_exists(tname): #ensure that the table exists in the woofdb
            print(f'\ttname {tname} does not exist in db, skipping...')
            continue

        process_woof(db_session, woof, tname)
'''old code
        #get the earliest sequence number from woofplot woof.id and work forward
        startsno = db_session.query(func.min(WoofData.seqno)).filter(WoofData.woof_id == woof.id).scalar()
        endsno = db_session.query(func.max(WoofData.seqno)).filter(WoofData.woof_id == woof.id).scalar()

        if DEBUG: 
            print(f'processing {woof.url} startseqno: {startsno} endseqno: {endsno}',flush=True)
        retn = get_woofdb_data(tname, startsno, endsno) #seqno, dt, data
        count = 0
        for ele in retn:
            exists = db_session.query(WoofData).filter_by(woof_id=woof.id, ts=ele[1]).first()
            if not exists:
                if DEBUG: 
                    print(f'ADDING {ele}')
                count += 1
                woofdata = WoofData(
                    seqno = ele[0],
                    ts = ele[1],
                    data = ele[2],
                    woof=woof
                )
                db_session.add(woofdata)
                db_session.commit()
                db_session.expunge(woofdata)
        print(f'Added {count} out of {len(retn)}')
'''

######################################
if __name__ == "__main__":
    main()

