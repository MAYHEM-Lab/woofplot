# woofplot-server.py
'''
    Author: Chandra Krintz, 
    License: UCSB BSD -- see LICENSE file in this repository
'''

import os, json
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS

app = Flask(__name__,static_folder='./build',static_url_path='/')
DEBUG=True

### CORS section
'''If your frontend app is running on a different port or domain (e.g., if it's served using a different web server or directly from the filesystem), you might encounter a CORS (Cross-Origin Resource Sharing) issue. This fixes it.  pip install flask-cors; in the app: CORS(app) or use the following '''
CORS(app)

'''
Note that flask automatically redirects routes without a final slash (/) to one with a final slash (e.g. /getmsg redirects to /getmsg/). Curl does not handle redirects but instead prints the updated url. The browser handles redirects (i.e. takes them). You should always code your routes with both a start/end slash.
'''
@app.route('/api/user/', methods=['GET'])
def getuser():
    # Retrieve the msg from url parameter of GET request 
    # and return MESSAGE response (or error or success)
    msg = request.args.get("msg", None)

    response = "admin"
    status = 200

    retn = jsonify(response),status
    if DEBUG:
        print(f"GET getuser() returning: {retn}")
        print(request.headers)

    # Return the response in json format with status code
    return retn

@app.route('/api/login/', methods=['POST']) 
def setuplogin(): 
    '''
    Implement a POST api for login.
    '''
    response = {}
    #only accept json content type
    if request.headers['content-type'] != 'application/json':
        return jsonify({"MESSAGE": "/api/login/ invalid content-type"}),400
    else:
        try:
            data = json.loads(request.data)
        except ValueError:
            return jsonify({"MESSAGE": "/api/login/ JSON load error"}),405
    if DEBUG:
        print(f"POST: data={data}")
    user = data['username']
    pw = data['password']
    status = 200

    retn = jsonify(user),status
    if DEBUG:
        print(f"GET setuplogin() returning: {retn}")
        print(request.headers)

    return retn

# Set the base route to be the react index.html
@app.route('/')
def index():
    return "<h1>Welcome to our server !!</h1>",200

    #use this instead if linking to a raact app on the same server
    #make sure and update the app = Flask(...) line above for the same
    #return app.send_static_file('index.html') 

def main():
    '''Use threaded option for concurrent accesses, default port is 8080
    '''
    localport = int(os.getenv("PORT", 8080))
    app.run(threaded=True, host='0.0.0.0', port=localport,debug=True)

if __name__ == '__main__':
    main()
