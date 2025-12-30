#!/bin/bash

sudo /etc/init.d/postgresql start   #make sure the database is started

# First check that redis-server is running (ps auxww |grep redis-server), if not start it with this:
redis-server --daemonize yes --logfile ./logs/woofplot-redis.log

# Clean out the queues and syart multiple background workers to load data in parallel
source woofplotenv/bin/activate
python clean_queue.py
rq worker default > ./logs/woofplot-worker1.log 2>&1 &
rq worker default > ./logs/woofplot-worker2.log 2>&1 &

# Start the server
python woofplot-server.py >> ./logs/woofplot-server.log 2>&1 &

