"""Shared test helpers. Every test gets a brand-new app, database and storage folder."""
import os
import tempfile
import unittest

from app import create_app


class ManualRunner:
    """A fake job runner that only RECORDS submitted jobs, so a test decides when they run.

    Lets us observe the 'pending' state and in-between progress deterministically,
    without sleeping or racing a real background thread.
    """

    def __init__(self):
        self.submitted = []

    def submit(self, fn, *args, **kwargs):
        self.submitted.append((fn, args, kwargs))

    def run_all(self):
        while self.submitted:
            fn, args, kwargs = self.submitted.pop(0)
            fn(*args, **kwargs)

    def shutdown(self, wait=True):
        pass


class AppTestCase(unittest.TestCase):
    config_overrides = {}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = {
            "TESTING": True,
            "DATABASE_PATH": os.path.join(self.tmp.name, "test.db"),
            "STORAGE_DIR": os.path.join(self.tmp.name, "storage"),
            "PROCESS_SYNC": True,          # run jobs inline -> results are ready when POST returns
            "RECOVER_ON_STARTUP": False,
        }
        self.config.update(self.config_overrides)
        self.app = create_app(self.config)
        self.client = self.app.test_client()

    def tearDown(self):
        self.app.extensions["job_runner"].shutdown()
        self.tmp.cleanup()

    # helpers ---------------------------------------------------------------------------
    @staticmethod
    def payload(names=("Alice Johnson", "Bob Smith", "Carol White"), **overrides):
        data = {
            "event_name": "Python Bootcamp 2026",
            "issued_by": "Tech Club",
            "issue_date": "2026-10-08",
            "recipients": [
                {"name": n, "email": f"{n.split()[0].lower()}@example.com"} for n in names
            ],
        }
        data.update(overrides)
        return data

    def post_job(self, payload=None):
        return self.client.post("/api/jobs", json=payload or self.payload())

    def use_manual_runner(self):
        runner = ManualRunner()
        self.app.extensions["job_runner"] = runner
        return runner
