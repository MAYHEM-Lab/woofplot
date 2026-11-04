#!/bin/bash
set -e
mkdir -p logs
PY="./woofplotenv/bin/python"

#uncomment this if you do not want your data decimated for the 60minute viewing window
#export DECIMATE_SKIP=1500

sudo /etc/init.d/postgresql start   #make sure the database is started

# First check that redis-server is running (ps auxww |grep redis-server), if not start it with this:
redis-server --daemonize yes --logfile ./logs/woofplot-redis.log

# Clean out the queues and syart multiple background workers to load data in parallel
nohup ${PY} clean_queue.py
nohup ${PY} -m rq worker live dispatch > ./logs/woofplot-worker1.log 2>&1 &
nohup ${PY} -m rq worker live dispatch > ./logs/woofplot-worker2.log 2>&1 &
nohup ${PY} -m rq worker backfill > ./logs/woofplot-workerbf1.log 2>&1 &
nohup ${PY} -m rq worker backfill > ./logs/woofplot-workerbf2.log 2>&1 &

nohup ${PY} -m rq worker history > logs/woofplot-history.log 2>&1 &
echo "Woofplot RQ workers started."

# Start server
nohup ${PY} woofplot-server.py > ./logs/woofplot-server.log 2>&1 &
echo "Woofplot server started."

