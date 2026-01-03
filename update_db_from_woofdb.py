# update_db_from_woofdb.py
'''
    Author: Chandra Krintz, 
    License: UCSB BSD -- see LICENSE file in this repository
'''
import os, sys, dotenv, argparse, random, math, json, time
from datetime import datetime, timedelta

#import the db interface in the sensor_data_tools directory
sys.path.append(os.path.join(os.path.dirname(__file__), '../sensor_data_tools', 'DB'))
import dbiface

from sqlalchemy import create_engine
from sqlalchemy.sql import func
from sqlalchemy.orm import scoped_session, sessionmaker

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
    #row: (191580.0, datetime.datetime(2024, 9, 11, 18, 25, 2, 526145), '172.31.31.189', '29.72:5:9:203:78:70:0.0:0.0:79:68:78:0:2024-09-11_18-24-58')
    #earlier, the final date in the data string needed correcting. This is no longer the case.
    cur = db.get_cursor()
    cur.execute(f"select * from {tname} where seqno >= {startsno} and seqno < {endsno} order by seqno")
    rows = cur.fetchall()
    retn = []
    for row in rows:
        #seqno, dt, ip, info, baro...dtmeas (13), epoch
        third = ':'.join(str(x) for x in row[4:-3])
        #update 2nd-to-last entry from 2024-03-19 05:34:09-07:00 to 2025-04-09_14-39-59
        dt = row[-2]
        formatted = dt.strftime('%Y-%m-%d_%H-%M-%S')
        third = f'{third}:{formatted}'
        retn.append((row[0],row[1],third))
    return retn


######################################
def get_woofdb_data(tname,startsno,endsno): #returns list of entries to write
    #of the form: ts, seqno, data (colon delimited data)
    if tname == 'wweather':
        return get_wweather(startsno, endsno)
    #elif tname.startswith('wu_'): #no need for special handling any more
        #return get_wu(tname,startsno, endsno)
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
    python update_db_from_woofdb.py args.json #see the json file for argument details
    This program fills in entries into the woofplot tables for all seqno's in the woofdb on the alerts system for 1 year prior to the earliest seqno in the woofplot table for that woof.  It computes 1 year using the timediff between seqnos (sampling rate).  If the program crashes, this program will skip the ones its already added and continue.  To fill in the holes in the db, use fill_holes_from_woofdb.py.
    '''
    global DEBUG, db
    parser = argparse.ArgumentParser(description='update woofplot table data from woofdb')
    parser.add_argument('json',action='store',help='json file holding the program args, see args file for details')
    pargs = parser.parse_args()

    if not os.path.isfile(pargs.json):
        print("Unable to open json file {}. \nUSAGE: python update_db_from_woofdb.py cf.json".format(pargs.json))
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
        outfile = args["fname"]
    except Exception as e:
        print(e)
        print("Unable to parse json file as expected. \nUSAGE: python3 update_db_from_woofdb.py cf.json")
        sys.exit(1)

    done_dict = {}
    if os.path.isfile(outfile):
        with open(outfile, "r") as f:
            for line in f:
                #1:woof://128.111.45.61/davisstations/wise-batt1:wise_batt1:288:18112
                line = line.strip()
                eles = line.split(':')
                woofid = eles[0]
                woofurl = f'{eles[1]}:{eles[2]}'
                nm = eles[3]
                sseqno = eles[4]
                eseqno = eles[5]
                #if there are multiples in the file, this will store the last one
                #which is what we want since we'll repeat ones that didn't finish
                done_dict[woofurl] = (sseqno,eseqno)

    #db is the woofdb from which we are loading
    db = dbiface.DBobj(woofdb,woofdbpwd,woofdbhost,woofdbuser)

    #db_session is the woofplot database
    woofs = db_session.query(Woofs).all()
    for woof in woofs:
        print(woof.id, woof.url)
        tname = get_tname(woof.url)
        if not db.table_exists(tname): #ensure that the table exists in the woofdb
            print(f"{tname} NOT FOUND IN DB! skipping...")
            continue

        #get the earliest sequence number from woofplot woof.id
        earliest_seqno = db_session.query(func.min(WoofData.seqno)).filter(WoofData.woof_id == woof.id).scalar()
        endsno = int(earliest_seqno)
        if DEBUG:
            print(f"Earliest seqno for woof_id {woof.id} and table {tname} is {endsno}...")
        if endsno < 10: #skip if the eariliest seqno is small (we have the head of the woof)
            print(f"At head of woof, skipping {tname}...")
            continue
        #get 5 data elements and compute their time difference (sampling rate)
        sample_data = db_session.query(WoofData.ts).filter(WoofData.woof_id == woof.id).order_by(WoofData.ts.desc()).limit(5).all()
        count = diffsum = 0
        for dt in sample_data:
            count += 1
            if count == 1:
                lastdt = dt[0]
                continue
            diff = lastdt-dt[0]
            assert diff.total_seconds() >= 0
            diffsum += diff.total_seconds()
            lastdt = dt[0]
        avg_sec_diff = diffsum/(count-1)
        measurements_per_day = int(86400/avg_sec_diff)
        total_samples = measurements_per_day * 365 #samples taken in a year
        startsno = endsno - total_samples
        if startsno < 0:
            startsno = measurements_per_day * 3 #start 3 days from sensor instantiation
        if DEBUG:
            print(f"orig_startsno: {endsno-total_samples}, startsno: {startsno}, endsno: {endsno}, total_samples: {total_samples}")

        #first check if we've already done this (and crashed out due to an error)
        PROCESSIT = True
        snpair = None
        donecount = end = start = 0
        if woof.url in done_dict:
            if DEBUG:
                print(f"found woof.url in done dictionary: {woof.url}")
            snpair = done_dict[woof.url]
            PROCESSIT = False
        if snpair is not None:
            start = int(snpair[0])
            end = int(snpair[1])
            #check that we have all of the seqnos
            donecount = db_session.query(func.count(WoofData.id))\
                .filter(WoofData.woof_id == woof.id)\
                .filter(WoofData.seqno.between(start, end))\
                .scalar()
            if DEBUG:
                print(f"donecount: {donecount}, end: {end}, start: {start}")
            if donecount < (end-start):
                PROCESSIT = True

        if PROCESSIT:
            print(f'processing {woof.url} donecount: {donecount} vs {end-start}')
            assert endsno >= startsno
            with open(outfile, "a") as f:
                f.write(f"{woof.id}:{woof.url}:{tname}:{startsno}:{endsno}\n")
            retn = get_woofdb_data(tname, startsno, endsno) #seqno, dt, data
            if DEBUG:
                print(f'\tavg_sec_diff: {int(avg_sec_diff)}, count: {count}, measperday: {measurements_per_day}, total_samples: {total_samples}')
                print(f'\tsql query: {startsno} - {endsno}')
                print(f'\tadding to woofplot DB; len: {len(retn)}')
                if len(retn) > 0:
                    print(f'first ele: {retn[0]}')
            for ele in retn:
                exists = db_session.query(WoofData).filter_by(woof_id=woof.id, ts=ele[1]).first()

                if not exists:
                    woofdata = WoofData(
                        seqno = ele[0],
                        ts = ele[1],
                        data = ele[2],
                        woof=woof
                    )
                    db_session.add(woofdata)
                    db_session.commit()
                    db_session.expunge(woofdata)

######################################
if __name__ == "__main__":
    main()

