from redis import Redis
from rq import Queue
from rq.registry import FailedJobRegistry

conn = Redis()
queue = Queue("history", connection=conn)
registry = FailedJobRegistry(queue=queue)

for job_id in registry.get_job_ids():
    print(f"Removing failed job: {job_id}")
    registry.remove(job_id, delete_job=True)
