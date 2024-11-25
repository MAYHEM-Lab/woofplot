import redis
from rq import Queue

# Create a shared Redis connection (use the same connection in all scripts)
redis_conn = redis.StrictRedis(host='localhost', port=6379, db=0)

# Create the RQ queue using the shared Redis connection
queue = Queue('default', connection=redis_conn)  # 'default' is the name of the queue

