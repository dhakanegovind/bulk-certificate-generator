from unittest import mock

from app import service
from tests.base import AppTestCase


class JobStatusTests(AppTestCase):
    def test_new_job_is_pending_with_zero_progress(self):
        self.use_manual_runner()
        job = self.post_job().get_json()
        status = self.client.get(f"/api/jobs/{job['id']}").get_json()
        self.assertEqual(status["status"], "pending")
        self.assertEqual(status["progress_percent"], 0)
        self.assertEqual(status["failures"], [])

    def test_progress_is_visible_while_processing(self):
        runner = self.use_manual_runner()
        job_id = self.post_job().get_json()["id"]
        snapshots = []
        real_render = service.render_certificate

        def spy(output_path, **kwargs):
            # Called right before the 2nd certificate ("Bob") is drawn.
            if kwargs["recipient_name"] == "Bob Smith":
                snapshots.append(self.client.get(f"/api/jobs/{job_id}").get_json())
            return real_render(output_path, **kwargs)

        with mock.patch("app.service.render_certificate", side_effect=spy):
            runner.run_all()

        mid = snapshots[0]
        self.assertEqual(mid["status"], "processing")
        self.assertEqual((mid["succeeded"], mid["pending"]), (1, 2))
        self.assertEqual(mid["progress_percent"], 33)

        final = self.client.get(f"/api/jobs/{job_id}").get_json()
        self.assertEqual(final["status"], "completed")
        self.assertEqual(final["progress_percent"], 100)
        self.assertIsNotNone(final["completed_at"])

    def test_unknown_job_returns_404(self):
        self.assertEqual(self.client.get("/api/jobs/doesnotexist").status_code, 404)

    def test_certificate_listing_filters_and_paginates(self):
        job_id = self.post_job(self.payload(recipients=[
            {"name": "Ok One", "email": "a@b.co"}, {"name": "", "email": "x"},
            {"name": "Ok Two", "email": "c@d.co"},
        ])).get_json()["id"]
        base = f"/api/jobs/{job_id}/certificates"

        failed = self.client.get(base + "?status=failed").get_json()
        self.assertEqual((failed["total"], len(failed["certificates"])), (1, 1))

        page = self.client.get(base + "?limit=1&offset=1").get_json()
        self.assertEqual(page["total"], 3)
        self.assertEqual(page["certificates"][0]["row_index"], 1)

        self.assertEqual(self.client.get(base + "?status=bogus").status_code, 400)
        self.assertEqual(self.client.get(base + "?limit=0").status_code, 400)
        self.assertEqual(self.client.get(base + "?limit=abc").status_code, 400)
