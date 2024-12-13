# woofplot-server.py
'''
    Author: Chandra Krintz, 
    License: UCSB BSD -- see LICENSE file in this repository
'''
import os, json, dotenv
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from flask_jwt_extended import JWTManager
DEBUG=False

def main(port):
    '''Use threaded option for concurrent accesses, default port is 8080
    '''
    localport = int(os.getenv("PORT", port))
    app.run(threaded=True, host='0.0.0.0', port=localport,debug=DEBUG)

if __name__ == '__main__':
    app = Flask(__name__,static_folder='./build',static_url_path='/')
    ### CORS section
    '''If your frontend app is running on a different port or domain (e.g., if it's served using a different web server or directly from the filesystem), you might encounter a CORS (Cross-Origin Resource Sharing) issue. This fixes it.  pip install flask-cors; in the app: CORS(app) or use the following '''
    CORS(app)

    #set up the app's context 
    with app.app_context():
        dotenv.load_dotenv()
        jwt_secret = os.environ.get("JWT_SECRET")
        tmp = os.environ.get("WPDEBUG")
        if tmp.lower() in ['true', '1']:
            DEBUG = True
        else: 
            DEBUG = False
        dburi = os.environ.get("SQLALCHEMY_DATABASE_URI")
        dbname = os.environ.get("database")
    port = os.environ.get("WPPORT")

    #setup JWT configurations and initialize the extensions
    app.config["JWT_SECRET_KEY"] = jwt_secret
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(minutes=5)
    app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(days=30)
    jwt = JWTManager(app)

    #cs190b infrastructure and utilities
    from db import db_session
    import routes

    #ask flask to shutdown the DB upon exit
    @app.teardown_appcontext
    def shutdown_session(exception=None):
        db_session.remove()
   
    #start the server app
    main(port)
