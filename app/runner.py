"""Runs jobs in the background so the HTTP request can return immediately.

A ThreadPoolExecutor is the simplest tool that works: no extra infrastructure (Redis,
RabbitMQ, ...). Trade-offs are documented in the README ("Design decisions").
"""
from concurrent.futures import ThreadPoolExecutor


class JobRunner:
    def __init__(self, workers=2, sync=False):
        self.sync = sync
        self._executor = None if sync else ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="cert-worker"
        )

    def submit(self, fn, *args, **kwargs):
        if self.sync:
            fn(*args, **kwargs)  # run inline, mostly for tests and debugging
            return None
        return self._executor.submit(fn, *args, **kwargs)

    def shutdown(self, wait=True):
        if self._executor is not None:
            self._executor.shutdown(wait=wait)
