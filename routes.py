# routes.py
'''
    Author: Chandra Krintz, 
    License: UCSB BSD -- see LICENSE file in this repository
'''
from __main__ import app
from __main__ import jwt
from __main__ import DEBUG
import sys, os, json
from datetime import timedelta, datetime, timezone
from flask import request, jsonify, g
from db import db_session
import utils 
from flask_jwt_extended import create_access_token, create_refresh_token, current_user, jwt_required   

'''
flask automatically redirects routes without a final slash (/) to one with a final slash 
'''
@app.route('/api/user/', methods=['GET'])
def getuser(): #only called by app without token
    #does not get invoked if no token is attached
    if "user" not in g:
        g.user = None
        return jsonify({"WOOFPLOT": "/api/user/ no user logged in"}),401
    return jsonify(g.user),200

@app.route('/api/peek/<path:url>', methods=['GET'])
def peekwoof(url): 
    res,OK = utils.cspot_get(url)
    if not OK:
        return jsonify(res),500
    typ = 'NUMERIC'
    val = res[0]
    try:
        val = float(res[0])
    except ValueError as e:
        typ = 'TEXT'
    ts = float(res[2])*1000
    if typ == 'NUMERIC':
        obj = {"typ": typ, "text": None, "number": val, "timestamp": ts}
    else: #TEXT
        obj = {"typ": typ, "text": val, "number": None, "timestamp": ts}
    return jsonify(obj),200

@app.route('/api/woof/', methods=['GET','POST'])
def getwoofs():
    responses = []
    ############  GET   ##############
    if request.method == 'GET':
        try:
            #this spawns jobs in background to load each woof's latest
            responses = utils.get_all_woofs_from_db()
        except Exception as e :
            return jsonify({"WOOFPLOT": f"/api/woof/ GET get_all_woofs_from_db error {e}"}),500
        return jsonify(responses), 200
    ############  POST ##############
    else:
        #create a db record for a woof the first time 
        #reuse an old record (same url) if available
        try:
            data = json.loads(request.data)
        except ValueError:
            return jsonify({"WOOFPLOT": "/api/woof/ POST JSON load error"}),405
        res,OK = utils.cspot_get(data["url"])
        if not OK:
            return jsonify(res),500
        #seqno must be a valid sequence number when creating a woof record for the first time
        seqno = int(res[5])

        #data is a dict with keys url, name, columns       #url is unique in DB  
        #columns is a list; columns and name get updated if values are different
        utils.add_or_update_woof_in_db(data,seqno)

        #spawn job in background to load the woof -- do the full JOB_LIMIT since user is working on adding columns
        if DEBUG:
            print(f'calling run_jobs from /apt/woof POST for {data["url"]}')
        utils.call_run_jobs(data["url"])

        return jsonify({}), 201
    return jsonify({f"WOOFPLOT": "/api/woof/ unknown method error {request.method}"}), 405

@app.route('/api/woof/<int:woof_id>', methods=['PUT', 'DELETE'])
def updatewoofs(woof_id):
    ######## DELETE ###########
    if request.method == 'DELETE': #delete the columns from the woof in the db
        utils.delete_woof_from_db(woof_id)
        return jsonify({}), 204
    ######## PUT ###########
    try: #updating columns for an existing woof
        data = json.loads(request.data)
    except ValueError:
        return jsonify({"WOOFPLOT": "/api/woof/ PUT JSON load error"}),405
    utils.add_or_update_woof_in_db(data)
    return jsonify({}), 204


@app.route('/api/query/', methods=['GET'])
def query(): 
    woofId = request.args.get('woofId')
    field = request.args.get('field')
    start = request.args.get('from')
    end = request.args.get('to')
    agg = request.args.get('aggregation')
    interval = request.args.get('interval')
    raw = None
    if 'raw_elements' in request.args:
        raw = request.args.get('raw_elements')
    retn,status = utils.get_woof_values(woofId,int(field),int(start),int(end),agg,interval,raw)
    return jsonify(retn), status

@app.route('/api/login/', methods=['POST']) 
def setuplogin(): 
    response = {}
    #only accept json content type
    if request.headers['content-type'] != 'application/json':
        return jsonify({"WOOFPLOT": "/api/login/ invalid content-type"}),400
    else:
        try:
            data = json.loads(request.data)
        except ValueError:
            return jsonify({"WOOFPLOT": "/api/login/ JSON load error"}),405
    if DEBUG:
        print(f"setuplogin POST: data={data}")
    username = data['username']
    password = data['password']
    user = utils.get_user_from_db(username)
    if not user or not user.check_password(password):
        return jsonify({"WOOFPLOT": "Incorrect username or password"}), 401
    if user and user.isLoggedIn:
        return jsonify({"WOOFPLOT": "User already logged in, log out first"}), 200
    g.user = username #global current user without requiring a jwt token
    if DEBUG:
        print(f"setuplogin: setting g.user={g.user}")

    #do not pass sensitive information here - it is not encrypted
    #you can add extra information to a jwt (nothing sensitive though!) via:
    #additional_claims = {"aud": "some_audience", "foo": "bar"}
    #access_token = create_access_token(..., additional_claims=additional_claims)
    response["username"]=user.username
    response["isAdmin"]=user.isAdmin
    response["token"]=create_access_token(identity=user.username)
    return jsonify(response), 200

@app.route('/api/changepassword/', methods=['POST']) 
def changepwd(): 
    #only accept json content type
    if request.headers['content-type'] != 'application/json':
        return jsonify({"WOOFPLOT": "/api/changepassword/ invalid content-type"}),400
    else:
        try:
            data = json.loads(request.data)
        except ValueError:
            return jsonify({"WOOFPLOT": "/api/changepassword/ JSON load error"}),405
    if DEBUG:
        print(f"changepwd POST: data={data}")
        print(f"\tg.user={g}")
    username = data['username']
    password = data['password']
    g.user = username
    result = utils.update_user_pwd(username,password)
    if result:
        return jsonify({"WOOFPLOT": "/api/changepassword/ User password changed"}), 200
    else:
        return jsonify({"WOOFPLOT": "/api/changepassword/ User password NOT changed"}), 200

@app.route('/api/logout/', methods=['POST']) 
def logout(): 
    g.user =  None #global current user without requiring a jwt token
    return jsonify({"WOOFPLOT": "User logged out"}), 200

@app.route('/api/retention/<int:weeks>', methods=['POST']) 
def update_retention(weeks): 
    set_state('retention',weeks)
    return jsonify({"WOOFPLOT": f"retention policy set to {weeks} weeks"}), 200
    
@app.route('/api/retention/', methods=['GET']) 
def retention(): 
    weeks = get_state('retention')
    return jsonify({weeks}), 200

# Set the base route to be the react index.html
@app.route('/')
def index():
    return app.send_static_file('index.html') 


