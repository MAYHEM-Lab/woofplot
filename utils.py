# db.py
'''
    Author: Chandra Krintz, 
    License: UCSB BSD -- see LICENSE file in this repository
'''
import traceback, sys, argparse, os, json
from datetime import datetime, timedelta
from passlib.hash import sha256_crypt
from sqlalchemy.sql import func
from sqlalchemy import UniqueConstraint, and_
from sqlalchemy.schema import DropTable
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import joinedload
from db import db_session
from models import Users, Woofs, Columns, WoofData
import time
import db
import cspot_utils
import tasks
from redis import Redis
from redis_config import queue
JOB_LIMIT = 100

DEBUG = os.environ.get("WPDEBUG")
secsmap = {
    "minute": 300,
    "hour": 3600,
    "day": 86400,
    "week": 604800
}

################
def decimate_array(arr, factor):
    return arr[::factor]

################
def get_woof_values(woofId,field,s,e,agg,interval): #between millisecond timestamps s and e
    start = s/1000 #convert the millisecond values to seconds
    startdt = datetime.fromtimestamp(start)
    end = e/1000
    enddt = datetime.fromtimestamp(end)
    timediff = end-start
    div = secsmap[interval]
    count_to_return = timediff/div
    woofvals = []
    responses = []
    if DEBUG:
        print(f'get_woof_values: {woofId}, {field}, {s}:{start}:{startdt}')
        print(f'{agg}, {interval}, {e}:{end}:{enddt}')
    try:
        #get the results from the db - decimate them randomly to return only the count_to_return
        #if there are fewer rows it will return all of them, note that we have to re-sort them as they
        #are returned randomly from the query. 
        #attributes: id, ts, seqno, data
        rand_rows = db_session.query(WoofData).filter(  
            and_(
                WoofData.woof_id == woofId,  # Filter by woof_id
                WoofData.ts >= startdt,    
                WoofData.ts <= enddt
            )
        ).order_by(func.random()).limit(count_to_return).all()
        if len(rand_rows) == 0:
            #no results
            retn = {f"WOOFPLOT": "get_woof_values nothing returned for woof {woofId}: {start}:{startdt}, {end}:{enddt}"}
            return retn,500

        #sort results
        results = sorted(rand_rows, key=lambda x: x.ts)

        #process results for returning
        TYP = None
        for result in results:
            response = {}  #woofId, field, ts, val
            response['woofId'] = woofId
            response['field'] = field
            val = ""
            TYP = 'string'
            try:
                val = float(result.data)
                TYP = 'float'
            except ValueError as e:
                tmpv = result.data.split(':')
                assert len(tmpv) > field
                val = tmpv[field]
            epoch = result.ts.timestamp()
            ts = int(epoch * 1000) #fend expects millis
            response['timestamp'] = ts
            response['value'] = val
            responses.append(response)

        if DEBUG:
            print(f"getting entry for woofID {woofId}")
        #add the latest if it got decimated out
        latest = get_woof_entry(woofId) #gets latest WoofData if no seqno is passed in
        epoch = latest.ts.timestamp()
        latest_ts = int(epoch*1000) #convert to millis and int
        last = responses[-1] #last entry in responses
        if latest_ts > last['timestamp']:
            response = {}
            response['woofId'] = woofId
            response['field'] = field
            response['timestamp'] = latest_ts
            assert TYP is not None
            if TYP == 'float': 
                response['value'] = float(latest.data)
            else:
                tmpv = latest.data.split(':')
                assert len(tmpv) > field
                response['value'] = tempv[field]
            responses.append(response)
    except Exception as e:
        print(f"Exception in get_woof_values: {e}")
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
            #a new woof better not have a seqno with value -1 a cspot_get 
            #should have been called to pass an actual value in
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
        print(f"Exception in add_or_update_woof_in_db: {e}")
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
        print("Exception in add_user_to_db: {}".format(e))
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
        print(f"Exception in update_user_pwd: {e}")
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
    return db_session.query(func.min(WoofData.seqno)).filter(WoofData.woof_id == woof_id).scalar()

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
def get_all_woof_entries(woofurl):
    woof = get_woof_from_db(woofurl)
    if DEBUG:
        print(f"get_all_woof_entries {woof}")
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
        if DEBUG:
            print(f'calling run_jobs from get_all_woofs_from_db for {woof.id}:{url}')
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
def run_jobs(woofurl):
    wid = get_woof_id_from_url(woofurl)
    run_jobs(wid)

################
def run_jobs(woofId,limit=JOB_LIMIT):
    #run background job to load woof entries ahead of the earliest sequence number
    try:
        if DEBUG:
            woofurl = get_woof_url_from_id(woofId)
            print(f"run_jobs: running background jobs for {woofurl}, limit: {limit}")
        #if limit == -1, get the most recent entries
        if limit == -1: #just call load_woof which loads a small number of the most recent entries
            job1 = queue.enqueue(tasks.woof_load_task, woofurl, -1, 72)
        else:
            earliest_seqno = get_earliest_seqno_from_woofId(woofId)
            job1 = queue.enqueue(tasks.woof_load_task, woofurl, earliest_seqno, limit)
        if DEBUG:
            print(f"{job1}")
    except Exception as e:
        print(f"Exception in run_jobs: {e}")

################
def load_woof(woofurl,endsn=-1, count=20): # limit the number loaded (count) to prevent bg job death/delays
    # Call senspot_get and put the data in the DB
    # Do this for cspot seqnos between startsn and endsn-1 inclusively (or latest if endsn=-1)
    # Returns the cspot return associated with the largest seqno retreived (latest if endsn=-1) or None on err

    #Cases:
    #   new woof (only pass in url), add count eles ending in the latest_seqno, add this seqno to the woof
    #   existing woof (only pass in url), add eles up to the latest_seq_no recorded in the woof
    #   seqno range 
    woof = get_woof_from_db(woofurl) #adds it if not there
    latest = woof.latest_seq_no
    if DEBUG:
        print(f"load_woof: {woofurl}, {endsn}, {count}: {latest}")
    retn = None #return the ts, seqno, data for last cspot entry loaded
    if latest == -1: #new woof: add the latest and work back through count
        res,OK = cspot_get(woofurl)
        if not OK:
            print(f'load_woof [latest]: cspot call failed {woofurl} trying again...')
            time.sleep(0.5)
            res,OK = cspot_get(woofurl)  #res format (indices: val=0, ts=2, seqno=5)
            #472.000000 time: 1732476793.9533109665 10.0.1.158 seq_no: 76147
            #val1:val2 time: 1732476793.9533109665 10.0.1.158 seq_no: 76147
            if not OK:
                print(f'load_woof [latest]: 2nd try cspot call failed {woofurl} failed')
                print(f"WOOFPLOT: latest load_woof error: cspot call failed")
                return None
        woof.latest_seq_no = endsn = int(res[5])
        if DEBUG:
            print(f"getting latest, got seqno: {endsn}")
        ts_exists = db_session.query(WoofData).filter(WoofData.seqno == endsn, WoofData.woof_id == woof.id).first()
        if not ts_exists:
            epoch = float(res[2])
            ts = datetime.fromtimestamp(epoch)
            if DEBUG:
                print(f'adding latest woofdata {ts}:{endsn}:{res[0]}')
            woofdata = WoofData(
                ts = ts,
                seqno = endsn,
                data = res[0],
                woof=woof 
            )
            retn = (ts,endsn,res[0]) #store off the latest
            db_session.add(woofdata)
            db_session.commit()
        else:
            retn = (ts_exists.ts,endsn,ts_exists.data) #store off the latest

    else: #latest != -1 ie this is not a new woof, latest holds it lastest_seq_no in the db
        if endsn == -1:  #case 2 -- get count entries less than latest
            endsn = latest
        #case 3 (else) - get count entries less than endsn passed in

    startsn = endsn-count
    for seqno in range(startsn, endsn):
        #check if we already did this and skip if so
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
            data = res[0],
            woof=woof 
        )
        db_session.add(woofdata)
        db_session.commit()
        if seqno == endsn-1: #save off the last one
            retn = (ts,seqno,res[0]) 
        
    return retn #ts, seqno, data for the last loaded

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
        load_woof(woofurl) #returns (ts, seqno, data)

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
        print(f"min: {earliest_seqno}, max: {latest_seqno}")

    if runjobs: 
        for woofurl in woofurls:
            print(f"running background jobs for {woofurl}")
            wid = woofmap[woofurl]
            run_jobs(wid)

###############################
if __name__ == "__main__":
    main()

