# db.py
'''
    Author: Chandra Krintz, 
    License: UCSB BSD -- see LICENSE file in this repository
'''
import os, sys, dotenv, argparse, random
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

dotenv.load_dotenv()
DEBUG = os.environ.get("WPDEBUG")
dburi = os.environ.get("SQLALCHEMY_DATABASE_URI")
dbname = os.environ.get("DATABASE")
engine = create_engine(dburi)
db_session = scoped_session(sessionmaker(
    autocommit=False, autoflush=False, bind=engine))

#Everything below happens after the db_session is created, thus can use the db
import utils
from models import Base

###############################
def init_db(cleandb = False):
    # import all modules to register them in the db metadata
    if not cleandb:
        Base.metadata.create_all(bind=engine)
    else:
        print("cleaning out the DB!")
        import woofplot_seed #seed data to fill the DB with if cleaned out
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        #create some users, sensors, and locations
        utils.add_users_in_list_to_db(woofplot_seed.users_list)
    print(f"The {dbname} DB has been checked!")


###############################
def main():
    parser = argparse.ArgumentParser(description='Running this file directly either cleans out the DB (-c flag) or checks that the DB is setup and ready to go for woofplot (no args). The program should exit without errors.')
    parser.add_argument('--cleandb','-c',action='store_true',
        help='set this if you want to clear out the database (all tables) and start from scratch with the woofplot seed data')
    args = parser.parse_args()
    init_db(args.cleandb)

###############################
if __name__ == "__main__":
    main()

