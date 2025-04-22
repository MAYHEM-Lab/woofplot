from datetime import datetime, timedelta
import utils
from rq import get_current_job

#start redis: redis-server 
#start workers via python rq worker &
#place job on queue via: from tasks import woof_load_task; ...job = queue.enqueue(woof_load_task, url, seqno)

def woof_load_task(url, seqno, count):
    job = get_current_job()
    taskId = job.id
    print(f"worker {taskId} loading {url} is starting at {datetime.now()}",flush=True)
    utils.load_woof(url,seqno,count)
    print(f"worker {taskId} loading {url} is done at {datetime.now()}",flush=True)

