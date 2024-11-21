# db.py
'''
    Author: Chandra Krintz, 
    License: UCSB BSD -- see LICENSE file in this repository
'''
import traceback, sys, argparse
from flask import jsonify
from datetime import datetime, timedelta
from passlib.hash import sha256_crypt
from sqlalchemy.sql import func
from sqlalchemy import UniqueConstraint
from sqlalchemy.schema import DropTable
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import joinedload
from db import db_session
from models import Users, Woofs, Columns
import cspot_utils

DEBUG=False
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
def get_woof_values(woofId,field,s,e,agg,interval):
    woof = None
    start = s/1000 #convert the millisecond values to seconds
    end = e/1000
    timediff = end-start
    div = secsmap[interval]
    count_to_return = timediff/div
    woofvals = []
    responses = []
    try:
        woof = get_woof_from_db_via_id(woofId) 
        if not woof:  
            #return jsonify({f"WOOFPLOT": "/api/query woof not found for id {woofId}"}),404
            print(f'did not find woof with id {woofId}')
            return
        url = woof.url
        startdt = datetime.fromtimestamp(start)
        seqno = -1 #get latest and work back
        while True:
            res,OK = cspot_get(url,seqno)
            if not OK:
                #return jsonify(res),500
                print(f'cspot call failed {url}, {seqno}')
                print(f'\t{woofId}, {field}, {s}, {e}, {agg}, {interval}')
                break
            ts = float(res[2])
            if seqno == -1:
                woof.seqno = int(res[5])
                db_session.commit()
            if ts < start:
                break
            seqno = int(res[5]) - 1

            #get the value float or string, if string, get appropriate field
            try:
                val = float(res[0])
            except ValueError as e:
                tmpv = res[0].split(':')
                assert len(tmpv) > field
                val = tmpv[field]

            #tuple is seqno (for debugging), timestamp, value
            woofvals.append((res[5],res[2],val))
        count = len(woofvals)
        if DEBUG:    
            print(f'{factor}')
            for idx in range(count-1,0,-1):
                print(f'{woofvals[idx]}')
            print()

        factor = 1 #no decimation
        if count_to_return < count:
            factor = int(count // count_to_return)
        decimated = decimate_array(woofvals,factor)
        count = len(decimated)
        for idx in range(count-1,0,-1):
            if DEBUG:
                print(f'{idx}: {decimated[idx]}')
            response = {}
            response['woofId'] = woofId
            response['field'] = field
            ele = decimated[idx]
            ts = float(ele[1]) * 1000 #fend expects millis
            response['timestamp'] = int(ts)
            response['value'] = ele[2]
            responses.append(response)
        #add the latest if it got decimated out
        latest_ts = int(float(woofvals[0][1])*1000) #convert to millis and int
        last = responses[-1]
        if latest_ts != last['timestamp']:
            response = {}
            response['woofId'] = woofId
            response['field'] = field
            response['timestamp'] = latest_ts
            response['value'] = woofvals[0][2]
            responses.append(response)
    except Exception as e:
        print(f"Exception in utils.add_or_update_woof_in_db: {e}")
        traceback.print_exc()
        return jsonify({f"WOOFPLOT": "/api/query exception {e}"}),500

    status = 200
    return jsonify(responses), status
    
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
    woofurl = data["url"]
    woof = None
    try:
        woof = get_woof_from_db(woofurl) 
        if not woof:  #create woof and columns
            woof = Woofs(
                url = woofurl,
                name = data["name"],
                latest_seq_no = seqno
            )
            for col in data["columns"]:
                column = Columns(
                    field = col["field"],
                    name = col["name"],
                    conversion = col["conversion"],
                    woof=woof #automatically associates column to woof
                )
            db_session.add(woof)
        else: #update the current_columns to match the ones passed in for the woof
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
            for curr in current_columns:
                field = curr.field
                if field not in client_field_list:
                    column_to_delete = db_session.query(Columns).filter(Columns.field == field, Columns.woof_id == woof.id).first()
                    db_session.delete(column_to_delete)

        db_session.commit()
    except Exception as e:
        print(f"Exception in utils.add_or_update_woof_in_db: {e}")
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
            print("utils.add_user_to_db: user already in DB with ID: {}".format(obj.id))
    except Exception as e:
        print("Exception in utils.add_user_to_db: {}".format(e))
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
            print(f"utils.update_user_pwd: user not found in DB: {unane}")
    except Exception as e:
        print(f"Exception in utils.update_user_pwd: {e}")
        traceback.print_exc()
    return False

################
def get_user_from_db(uname):
    return db_session.query(Users).filter(Users.username == uname).first()

################
def get_woof_from_db(url):
    return db_session.query(Woofs).filter(Woofs.url == url).first()

################
def get_woof_from_db_via_id(id):
    return db_session.query(Woofs).filter(Woofs.id == id).first()

################
def delete_woof_from_db(id):
    woof_to_delete = db_session.query(Woofs).filter(Woofs.id == id).first()
    db_session.delete(woof_to_delete)
    db_session.commit()

################
def get_all_woofs_from_db():
    # Query all Woof objects along with their associated Columns using eager loading
    woofs = db_session.query(Woofs).options(joinedload(Woofs.columns)).all()
    print(f"{woofs}")

    # Create a list of dictionaries to represent the result
    res = []
    for woof in woofs:
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

###############################
def main():
    parser = argparse.ArgumentParser(description='Running this file directly either cleans out the DB (-c flag) or checks that the DB is setup and ready to go for woofplot (no args). The program should exit without errors.')
    parser.add_argument('--woofid',action='store',default=3,help='woofid')
    parser.add_argument('--field',action='store',default=0,help='fieldid')
    parser.add_argument('--start',action='store',default=1732219800000,help='start ts')
    parser.add_argument('--end',action='store',default=1732222800000,help='end ts')
    parser.add_argument('--agg',action='store',default='average',help='aggregation')
    parser.add_argument('--intv',action='store',default='minute',help='interval')
    args = parser.parse_args()
    #60 minutes 
    print('comment out jsonify in this function to get this to work')
    get_woof_values(args.woofid,args.field,args.start,args.end,args.agg,args.intv)


###############################
if __name__ == "__main__":
    main()

