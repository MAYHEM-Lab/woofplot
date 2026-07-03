from datetime import datetime, timedelta
import utils
from rq import get_current_job
from redis_config import redis_conn
from rq import Worker

for w in Worker.all(connection=redis_conn):
    print(w.name)
    print(w.get_state())

    job = w.get_current_job()
    if job:
        print(job.id)
        print(job.func_name)
        print(job.started_at)
