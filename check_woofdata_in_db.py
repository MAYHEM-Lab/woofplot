# update_db_from_woofdb.py
'''
    Author: Chandra Krintz, 
    License: UCSB BSD -- see LICENSE file in this repository
'''
import os, sys, dotenv, argparse, random, math, json, time, traceback
from datetime import datetime, timedelta

from sqlalchemy import create_engine, and_
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
def main():
    ''' 
    python check_woofdata_in_db.py args.json #see the json file for argument details
    '''
    global DEBUG, db
    parser = argparse.ArgumentParser(description='print out data in table from a specific woofID (get the woofID from the woofs table')
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
        woofId = args["woofId"]
        fdt = args["firstdt"]
    except Exception as e:
        print(e)
        print("Unable to parse json file as expected. \nUSAGE: python3 getWoofData.py cf.json")
        sys.exit(1)

    firstdt = datetime.strptime(fdt, "%Y-%m-%d %H:%M:%S") #2025-04-21 14:41:10

    try:
        #db_session is the woofplot database
        woofdata = db_session.query(WoofData).filter(  
                and_(
                    WoofData.woof_id == woofId,  # Filter by woof_id
                    WoofData.ts > firstdt 
                ) 
            ).order_by(WoofData.seqno).all()
        #delete all data after firstdt
        latest = -1
        for woofd in woofdata:
            latest = woofd.seqno #ordered by seqno, so this will be the greatest value at end
            print(f'id:{woofd.id}/{woofd.seqno}, ts:{woofd.ts}, data:{woofd.data}')
            db_session.delete(woofd) #be careful with this!
        db_session.commit()
        latest = db_session.query(func.max(WoofData.seqno)).filter_by(woof_id=woofId).scalar()
        assert latest != -1
        assert latest != None
        #update the woof's latest_seq_no
        retn =  db_session.query(Woofs).with_entities(Woofs.url).filter(Woofs.id == woofId).first()
        assert retn
        url = retn[0]
        woof = db_session.query(Woofs).filter_by(url=url).first()
        woof.latest_seq_no = latest
        print(f'woof_latest = {woof.latest_seq_no}; latest = {latest}')
        db_session.commit()
    except Exception as e:
        print(f"Exception in check_woofdata_in_db.py:main: {e}")
        traceback.print_exc()

######################################
if __name__ == "__main__":
    main()

