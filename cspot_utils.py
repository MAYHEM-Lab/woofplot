import requests, json, os, sys, argparse, io, time, dotenv
from datetime import datetime, date, timedelta
from subprocess import call,Popen,PIPE
import logging as log

DEBUG = False
dotenv.load_dotenv()
CSPOT_DIR = os.environ.get("CSPOT_DIR")
DONTUPDATEWOOFS=False
WOOF_PREFIX_DEF = 'woof://128.111.45.24:53970/mnt/monitor/'
WOOF_PREFIX_PROD='woof://128.111.45.83:57850/mnt/monitor/'

#########################
def cspot_put(cmdecho,cmdcspot): #pipe data via echo to cspot put
    result = ""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    firstcmd = Popen(cmdecho, stdout=PIPE)
    p = Popen(cmdcspot, stdin=firstcmd.stdout, stdout=PIPE, stderr=PIPE)

    result, err = p.communicate()
    if p.returncode != 0:
        log.info("{} -- WARNING: Unable to communicate with remote cspot: {}\n{}".format(now,cmdcspot,err))
        print("WARNING: Unable to communicate with remote cspot: {}\n\tRetrying one time...".format(cmdcspot))
        #try a second time
        result = ""
        firstcmd = Popen(cmdecho, stdout=PIPE)
        p = Popen(cmdcspot, stdin=firstcmd.stdout, stdout=PIPE, stderr=PIPE)
        result, err = p.communicate()
        #give up on second failure
        if p.returncode != 0:
            log.info("{} -- FAILURE: Unable to communicate with remote cspot: {}\n{}".format(now,cmdcspot,err))
            print("FAILURE: Unable to communicate with remote cspot: {}".format(cmdcspot))
            raise IOError(err)
    return result,err

#########################
def cspot_send_jumbo(data,woof,senspot_dir=CSPOT_DIR,wprefix=WOOF_PREFIX_DEF,datatype="F",forward=False): 
    cspot_send(data,woof,senspot_dir=senspot_dir,wprefix=wprefix,datatype=datatype,JUMBOFLAG=True,forward=forward)

#########################
def cspot_send(data,woof,senspot_dir=CSPOT_DIR,wprefix=WOOF_PREFIX_DEF,datatype="F",JUMBOFLAG=False,forward=False): 
    '''
    default type is float, can pass in "S" for string
    woof = "woof://128.111.45.24:53970/mnt/monitor/cjktestwoof"
    echo data | /root/bin/senspot-put-jumbo -W $WNAME -T d
    echo -e "text_data" | /root/bin/senspot-put-jumbo -W $WNAME -T S
    data must be type str (even if it is a float datatype)

    usage:
    cspot_send_jumbo(data,hostwf,datatype="S",wprefix=pref)
    cspot_send_jumbo(data,hostwf,wprefix=pref)
    cspot_send_jumbo(signal_strength,"pizero-03.ss07",wprefix=WOOF_PREFIX_PROD)
    '''

    assert datatype=="F" or datatype=="S" #nothing else is handled
    assert type(data) == str
    wf = "{}{}".format(wprefix,woof)
    if JUMBOFLAG:
        cspotcmd = "{0}/senspot-put-jumbo".format(senspot_dir)
    else:
        cspotcmd = "{0}/senspot-put".format(senspot_dir)

    if DEBUG:
        print("here cspot_send: {} {} {} {}".format(cspotcmd,wf,data,datatype))
        print(cspotcmd)
    if DONTUPDATEWOOFS:
        return
    cmdlist = None
    if datatype == "F": #sending doubles
        cmdlistecho = ['/bin/echo', data]
        if forward:
            cmdlistput = [cspotcmd, '-W', wf, "-T", "d", "-H", "senspot_forward"]
        else:
            cmdlistput = [cspotcmd, '-W', wf, "-T", "d"]
    else: #sending string
        ds = "{}".format(data)
        cmdlistecho = ['/bin/echo', "-en", ds]
        if forward:
            cmdlistput = [cspotcmd, '-W', wf, "-T", "S", "-H", "senspot_forward"]
        else:
            cmdlistput = [cspotcmd, '-W', wf, "-T", "S"]
    #call cspot put
    result,err = cspot_put(cmdlistecho,cmdlistput)
    return result,err

#########################
def senspot_get(wf,senspot_dir=CSPOT_DIR,seqno=-1,JUMBOFLAG=False):
    #senspot-get -W woof://128.111.45.24:53970/mnt/monitor/cjkpi303-dht
    '''usage:
    senspot_get(woof)
    senspot_get(woof://128.111.45.24:53970/mnt/monitor/cjkpi303-dht)
    '''
    if JUMBOFLAG:
        cspotcmd = "{0}/senspot-get-jumbo".format(senspot_dir)
    else:
        cspotcmd = "{0}/senspot-get".format(senspot_dir)
    if DEBUG:
        print("senspot_get: {} {} {}".format(cspotcmd,wf,seqno))
    if DONTUPDATEWOOFS:
        return
    result = ""
    if seqno == -1:
        p = Popen([cspotcmd, '-W', wf], stdout=PIPE, stderr=PIPE)
    else:
        sn = str(seqno)
        p = Popen([cspotcmd, '-W', wf, '-S', sn], stdout=PIPE, stderr=PIPE)
    res,err = p.communicate()
    return res,p.returncode,err

#########################
def cspot_get(woof,senspot_dir=CSPOT_DIR,wprefix=WOOF_PREFIX_DEF,seqno=-1,JUMBOFLAG=False): #default type is float, can pass in "S" for string
    #woof = "woof://128.111.45.24:53970/mnt/monitor/cjktestwoof"
    #senspot-get -W woof://128.111.45.24:53970/mnt/monitor/cjkpi303-dht
    '''usage:
    cspot_get(woofname,woofprefix)
    '''
    wf = "{}{}".format(wprefix,woof)
    return senspot_get(wf,senspot_dir=senspot_dir,seqno=seqno,JUMBOFLAG=JUMBOFLAG)

