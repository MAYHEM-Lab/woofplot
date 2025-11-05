from datetime import datetime, timedelta
import utils
from rq import get_current_job
from redis_config import redis_conn

#start redis: redis-server 
#start workers via python rq worker &
#place job on queue via: from tasks import woof_load_task; ...job = queue.enqueue(woof_load_task, url, seqno)

def woof_load_task(url, seqno, count, *, woof_id=None, latest=None):
    job = get_current_job()
    dedupe_key = None
    if seqno == -1:
        assert latest
        dedupe_key = f"woofload:dedupe:{woof_id}:{latest}:{count}" if woof_id is not None else None
    else:
        dedupe_key = f"woofload:dedupe:{woof_id}:{seqno}:{count}" if woof_id is not None else None
    print(f"woof_load_task [{job.id}] loading {url} start={seqno} count={count} latest={latest} dedupe={dedupe_key} at {datetime.now()}", flush=True)
        

    try:
        # This is the idempotent loader (check for seqno's before requesting/adding)
        err = utils.load_woof(url, seqno, count)
        if err is None: 
            print(f"PROBLEM in background load_woof task: [{job.id}] {url} {seqno} {count}", flush=True)
        else:
            pass
            # success → allow immediate re-enqueue
            #if dedupe_key:
                #redis_conn.delete(dedupe_key)
        print(f"[{job.id}] done {url} at {datetime.now()}", flush=True)
    except Exception as e:
        # On failure, keep the dedupe key; the TTL prevents instant duplicate enqueues
        # (We can also log or move job to a retry queue here.)
        print(f"[{job.id}] error: {e}", flush=True)
        raise

#####################
def call_enqueue_woof_load_jobs(wid, url, seqno):
    job = get_current_job()
    dedupe_key = f"woofload:enqueue_jobs:dedupe:{wid}:{seqno}" #in case we want to delete it...
    print(f"woof_load_task [{job.id}] {url} enqueue_jobs: dedupe={dedupe_key} at {datetime.now()}", flush=True)
    try:
        # This is the idempotent loader (check for seqno's before requesting/adding)
        err = utils.enqueue_woof_load_jobs(wid, url, seqno)
        if err is None: 
            print(f"PROBLEM in background enqueue_jobs task: [{job.id}] {url} {seqno}", flush=True)
        print(f"[{job.id}] done {url} at {datetime.now()}", flush=True)
    except Exception as e:
        # On failure, keep the dedupe key; the TTL prevents instant duplicate enqueues
        # (We can also log or move job to a retry queue here.)
        print(f"[{job.id}] enqueue_jobs error: {e}", flush=True)
        raise
