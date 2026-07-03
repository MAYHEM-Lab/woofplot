"""
Redis/RQ queue configuration for woofplot.

This keeps a backward-compatible `queue` name for legacy code, but adds
separate queues so live refresh work cannot be starved by historical backfill.
"""

import os
import redis
from rq import Queue

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB = int(os.environ.get("REDIS_DB", "0"))

redis_conn = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)

# Backward compatibility: existing code imports `queue`.
queue = Queue("default", connection=redis_conn)

# New priority-separated queues.
live_q = Queue("live", connection=redis_conn)
dispatch_q = Queue("dispatch", connection=redis_conn)
backfill_q = Queue("backfill", connection=redis_conn)

ALL_QUEUE_NAMES = ("live", "dispatch", "backfill", "default")
