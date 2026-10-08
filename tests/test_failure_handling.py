from pathlib import Path
from unittest import mock

from app import service
from tests.base import AppTestCase


class IndividualFailureTests(AppTestCase):
    def test_unexpected_error_in_one_certificate_does_not_stop_the_others(self):
        real_render = service.render_certificate

        def flaky(output_path, **kwargs):
            if kwargs["recipient_name"] == "Bob Smith":
                # simulate a half-written file followed by a crash
                Path(output_path).write_bytes(b"garbage")
                raise RuntimeError("disk exploded")
            return real_render(output_path, **kwargs)

        with mock.patch("app.service.render_certificate", side_effect=flaky), \
                self.assertLogs("app.service", level="ERROR"):  # the error IS logged (and silenced here)
            job = self.post_job().get_json()

        self.assertEqual(job["status"], "completed_with_errors")
        self.assertEqual((job["succeeded"], job["failed"]), (2, 1))

        detail = self.client.get(f"/api/jobs/{job['id']}").get_json()
        failure = detail["failures"][0]
        self.assertEqual(failure["recipient_name"], "Bob Smith")
        self.assertEqual(failure["row_index"], 1)
        self.assertIn("disk exploded", failure["error"])

        # the broken half-written file was cleaned up
        pdfs = list((Path(self.config["STORAGE_DIR"]) / job["id"]).glob("*.pdf"))
        self.assertEqual(len(pdfs), 2)

    def test_unrenderable_name_fails_only_that_certificate(self):
        payload = self.payload(recipients=[
            {"name": "Asha Rao", "email": "a@b.co"},
            {"name": "गोविंद", "email": "g@b.co"},
            {"name": "Ravi Kumar", "email": "r@b.co"},
        ])
        job = self.post_job(payload).get_json()
        self.assertEqual(job["status"], "completed_with_errors")
        failure = self.client.get(f"/api/jobs/{job['id']}").get_json()["failures"][0]
        self.assertEqual(failure["row_index"], 1)
        self.assertIn("cannot render", failure["error"])

    def test_job_is_failed_when_every_certificate_fails(self):
        with mock.patch("app.service.render_certificate", side_effect=RuntimeError("boom")), \
                self.assertLogs("app.service", level="ERROR"):
            job = self.post_job().get_json()
        self.assertEqual(job["status"], "failed")
        self.assertEqual((job["succeeded"], job["failed"]), (0, 3))

    def test_crash_of_the_whole_job_is_recorded_not_left_processing(self):
        runner = self.use_manual_runner()
        job_id = self.post_job().get_json()["id"]
        with mock.patch("app.service._generate_one", side_effect=RuntimeError("db gone")), \
                self.assertLogs("app.service", level="ERROR"):
            runner.run_all()
        job = self.client.get(f"/api/jobs/{job_id}").get_json()
        self.assertEqual(job["status"], "failed")
        self.assertIn("db gone", job["error"])
