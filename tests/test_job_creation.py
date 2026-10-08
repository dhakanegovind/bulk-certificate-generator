from tests.base import AppTestCase


class CreateJobTests(AppTestCase):
    def test_create_job_returns_202_with_job_details(self):
        response = self.post_job()
        self.assertEqual(response.status_code, 202)
        body = response.get_json()
        self.assertEqual(body["total"], 3)
        self.assertEqual(body["event_name"], "Python Bootcamp 2026")
        self.assertEqual(body["title"], "Certificate of Completion")  # default applied
        self.assertIn("id", body)
        self.assertEqual(response.headers["Location"], f"/api/jobs/{body['id']}")

    def test_one_request_creates_one_certificate_row_per_recipient(self):
        job = self.post_job().get_json()
        listing = self.client.get(f"/api/jobs/{job['id']}/certificates").get_json()
        self.assertEqual(listing["total"], 3)
        self.assertEqual([c["recipient_name"] for c in listing["certificates"]],
                         ["Alice Johnson", "Bob Smith", "Carol White"])

    def test_job_is_queued_not_generated_inside_the_request(self):
        runner = self.use_manual_runner()
        body = self.post_job().get_json()
        self.assertEqual(body["status"], "pending")
        self.assertEqual(body["pending"], 3)
        self.assertEqual(len(runner.submitted), 1)  # handed to the background runner

    def test_recipient_input_is_normalised(self):
        payload = self.payload(recipients=[{"name": "  Dana Lee  ", "email": " DANA@Example.COM "}])
        job = self.post_job(payload).get_json()
        cert = self.client.get(f"/api/jobs/{job['id']}/certificates").get_json()["certificates"][0]
        self.assertEqual(cert["recipient_name"], "Dana Lee")
        self.assertEqual(cert["recipient_email"], "dana@example.com")
