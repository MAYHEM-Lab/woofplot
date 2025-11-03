from redis_config import queue as myqueue  # uses your shared queue
from rq.job import Job
from rq.registry import FailedJobRegistry, StartedJobRegistry, FinishedJobRegistry
from redis_config import redis_conn
from rq import Queue

# List queued job IDs
print("Queued job IDs:", myqueue.job_ids)

# Or get Job objects with full info
for job in myqueue.jobs:
    print(f"{job.id}: {job.func_name} args={job.args} kwargs={job.kwargs} status={job.get_status()}")


q = Queue('default', connection=redis_conn)

failed = FailedJobRegistry(queue=q)
started = StartedJobRegistry(queue=q)
finished = FinishedJobRegistry(queue=q)

print("Failed:", failed.get_job_ids())
print("Running:", started.get_job_ids())
print("Recently finished:", finished.get_job_ids())

