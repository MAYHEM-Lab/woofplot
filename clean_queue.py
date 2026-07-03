from rq import Queue
from rq.job import Job
from rq.exceptions import NoSuchJobError
from rq.registry import (
    FailedJobRegistry,
    FinishedJobRegistry,
    StartedJobRegistry,
    DeferredJobRegistry,
    ScheduledJobRegistry,
)

from redis_config import redis_conn

QUEUE_NAMES = [
    "live",
    "dispatch",
    "backfill",
]


def safe_remove(registry, jid, *, delete_job_hash=True):
    try:
        registry.remove(jid, delete_job=delete_job_hash)
    except NoSuchJobError:
        try:
            registry.remove(jid, delete_job=False)
        except Exception:
            pass


def prune_queue_and_registries(q: Queue, *, prune_finished=True, empty_queued=True):
    failed = FailedJobRegistry(queue=q)
    started = StartedJobRegistry(queue=q)
    finished = FinishedJobRegistry(queue=q)
    deferred = DeferredJobRegistry(queue=q)
    scheduled = ScheduledJobRegistry(queue=q)

    print(f"\n=== queue:{q.name} ===")
    print(f"[queued] {len(q.job_ids)} ids")

    if empty_queued:
        q.empty()
        print("  queued jobs emptied")

    def prune_registry(registry, name, delete_hash=True):
        ids = registry.get_job_ids()
        print(f"[{name}] {len(ids)} ids")

        removed, ghosts = 0, 0

        for jid in ids:
            try:
                job = Job.fetch(jid, connection=q.connection)

                if name == "finished" and not prune_finished:
                    continue

                job.delete()
                registry.remove(jid, delete_job=False)
                removed += 1

            except NoSuchJobError:
                safe_remove(registry, jid, delete_job_hash=False)
                ghosts += 1

        print(f"  removed={removed}, ghosts_cleaned={ghosts}")

    prune_registry(failed, "failed")
    prune_registry(started, "started")
    prune_registry(deferred, "deferred")
    prune_registry(scheduled, "scheduled")
    prune_registry(finished, "finished")


if __name__ == "__main__":
    for name in QUEUE_NAMES:
        q = Queue(name, connection=redis_conn)
        prune_queue_and_registries(q, prune_finished=True, empty_queued=True)
