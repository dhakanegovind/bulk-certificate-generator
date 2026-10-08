import time

from app import create_app, service
from app.db import connect
from tests.base import AppTestCase


def wait_for(client, job_id, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").get_json()
        if job["status"] not in ("pending", "processing"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish in time")


class RealBackgroundProcessingTests(AppTestCase):
    """Uses the real thread pool (no fake runner): the way the app really runs."""
    config_overrides = {"PROCESS_SYNC": False}

    def test_request_returns_before_work_finishes_and_job_completes_later(self):
        names = [f"Person{i} Test" for i in range(40)]
        response = self.post_job(self.payload(names))
        self.assertEqual(response.status_code, 202)
        job = wait_for(self.client, response.get_json()["id"])
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["succeeded"], 40)


class CrashRecoveryTests(AppTestCase):
    def test_unfinished_jobs_are_resumed_on_startup(self):
        # 1. Create a job but never run it, as if the server died right after accepting it.
        self.use_manual_runner()
        job_id = self.post_job().get_json()["id"]
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}").get_json()["status"], "pending")

        # 2. "Restart" the server against the same database with recovery switched on.
        restarted = create_app({**self.config, "RECOVER_ON_STARTUP": True})
        job = restarted.test_client().get(f"/api/jobs/{job_id}").get_json()
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["succeeded"], 3)

    def test_reprocessing_does_not_redo_finished_certificates(self):
        job_id = self.post_job().get_json()["id"]
        before = self.client.get(f"/api/jobs/{job_id}/certificates").get_json()["certificates"]
        service.process_job(self.config["DATABASE_PATH"], self.config["STORAGE_DIR"], job_id)
        after = self.client.get(f"/api/jobs/{job_id}/certificates").get_json()["certificates"]
        self.assertEqual(before, after)
        self.assertEqual(service.recover_unfinished_jobs(self.config["DATABASE_PATH"]), [])
