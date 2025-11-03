# prune_rq.py
from redis_config import queue, redis_conn
from rq import Queue
from rq.job import Job
from rq.exceptions import NoSuchJobError
from rq.registry import FailedJobRegistry, FinishedJobRegistry, StartedJobRegistry, DeferredJobRegistry

def safe_remove(registry, jid, *, delete_job_hash=True):
    """Remove jid from registry; if the job hash is already gone, ignore."""
    try:
        # registry.remove will delete the job hash if delete_job=True (default),
        # but we may already have a missing job, so toggle accordingly.
        registry.remove(jid, delete_job=delete_job_hash)
    except NoSuchJobError:
        # Job hash already gone; ensure the id is removed from the registry set.
        # Some RQ versions still raise here; call again with delete_job=False.
        try:
            registry.remove(jid, delete_job=False)
        except Exception:
            pass

def prune_queue_and_registries(q: Queue, *, prune_finished=False):
    failed   = FailedJobRegistry(queue=q)
    started  = StartedJobRegistry(queue=q)
    finished = FinishedJobRegistry(queue=q)
    deferred = DeferredJobRegistry(queue=q)

    def prune_registry(registry, name, delete_hash=True):
        ids = registry.get_job_ids()
        print(f"[{name}] {len(ids)} ids")
        removed, ghosts = 0, 0
        for jid in ids:
            try:
                # Try to fetch the job hash
                job = Job.fetch(jid, connection=q.connection)
                # Optional: perform extra checks or delete based on age/status
                if name == "finished" and not prune_finished:
                    continue
                # Delete job hash + remove from registry
                job.delete()  # removes Redis hash
                registry.remove(jid, delete_job=False)  # ensure set membership cleaned
                removed += 1
            except NoSuchJobError:
                # Ghost reference: remove ID from registry set
                safe_remove(registry, jid, delete_job_hash=False)
                ghosts += 1
        print(f"  removed={removed}, ghosts_cleaned={ghosts}")

    # Note: queue.job_ids are only the “queued/pending” jobs, not in registries.
    print(f"[queue:{q.name}] queued={len(q.job_ids)} -> {q.job_ids[:20]}")

    # Clean registries
    prune_registry(failed,   "failed")
    prune_registry(started,  "started")     # will typically be small; stale if workers died
    prune_registry(deferred, "deferred")    # scheduled or dependent jobs
    prune_registry(finished, "finished")    # set prune_finished=True to actually purge

if __name__ == "__main__":
    # Uses your shared queue/connection from redis_config.py
    prune_queue_and_registries(queue, prune_finished=True)

