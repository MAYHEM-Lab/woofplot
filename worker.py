from redis_config import queue
from rq import Worker, Connection

# Set up a worker for the queue
with Connection():
    worker = Worker([queue])
    print("Worker is starting...")
    worker.work()  # This blocks and processes jobs in the queue

