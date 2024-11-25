from datetime import datetime, timedelta
import utils

#start redis: redis-server 
#start workers via python rq worker &
#place job on queue via: from tasks import woof_load_task; ...job = queue.enqueue(woof_load_task, url, seqno)

def woof_load_task(url, seqno, count):
    print(f"worker loading {url} is starting at {datetime.now()}")
    utils.load_woof(url,seqno,count)
    print(f"worker loading {url} is done at {datetime.now()}")

