import unittest

from app.validation import ValidationError, validate_job_request, validate_recipient
from tests.base import AppTestCase


class RecipientValidationUnitTests(unittest.TestCase):
    def test_valid_recipient(self):
        clean, error = validate_recipient({"name": "Asha Rao", "email": "asha@example.com"})
        self.assertIsNone(error)
        self.assertEqual(clean, {"name": "Asha Rao", "email": "asha@example.com"})

    def test_invalid_recipients(self):
        bad_inputs = [
            {"name": "", "email": "a@b.com"},                 # empty name
            {"name": "   ", "email": "a@b.com"},              # blank name
            {"email": "a@b.com"},                             # missing name
            {"name": "Asha", "email": "not-an-email"},        # bad email
            {"name": "Asha", "email": "a@b"},                 # no TLD
            {"name": "Asha"},                                 # missing email
            {"name": 123, "email": "a@b.com"},                # wrong type
            {"name": "A" * 101, "email": "a@b.com"},          # too long
            {"name": "Line\nBreak", "email": "a@b.com"},      # control character
            "just a string",                                  # not an object
            None,
        ]
        for raw in bad_inputs:
            with self.subTest(raw=raw):
                clean, error = validate_recipient(raw)
                self.assertIsNone(clean)
                self.assertTrue(error)

    def test_all_problems_reported_together(self):
        _, error = validate_recipient({"name": "", "email": "bad"})
        self.assertIn("name", error)
        self.assertIn("email", error)


class JobRequestValidationUnitTests(unittest.TestCase):
    def valid(self, **overrides):
        data = {"event_name": "E", "issued_by": "I", "recipients": [{"name": "A", "email": "a@b.co"}]}
        data.update(overrides)
        return data

    def test_missing_required_fields_are_all_reported(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_job_request({}, max_recipients=10)
        fields = {d["field"] for d in ctx.exception.details}
        self.assertEqual(fields, {"event_name", "issued_by", "recipients"})

    def test_bad_date_rejected(self):
        for bad in ("08-10-2026", "2026-13-40", 20261008):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                validate_job_request(self.valid(issue_date=bad), max_recipients=10)

    def test_non_object_body_rejected(self):
        for bad in (None, [], "text", 5):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                validate_job_request(bad, max_recipients=10)


class ValidationApiTests(AppTestCase):
    config_overrides = {"MAX_RECIPIENTS": 5}

    def test_invalid_job_request_returns_400_and_creates_nothing(self):
        response = self.client.post("/api/jobs", json={"recipients": []})
        self.assertEqual(response.status_code, 400)
        error = response.get_json()["error"]
        self.assertEqual(error["code"], "validation_error")
        self.assertTrue(error["details"])

    def test_non_json_body_returns_400(self):
        response = self.client.post("/api/jobs", data="not json", content_type="text/plain")
        self.assertEqual(response.status_code, 400)

    def test_too_many_recipients_rejected(self):
        names = [f"Person{i} X" for i in range(6)]
        response = self.post_job(self.payload(names))
        self.assertEqual(response.status_code, 400)
        self.assertIn("Too many", response.get_json()["error"]["details"][0]["message"])

    def test_invalid_recipients_do_not_block_valid_ones(self):
        payload = self.payload(recipients=[
            {"name": "Good One", "email": "good@example.com"},
            {"name": "", "email": "bad"},
            {"name": "Good Two", "email": "two@example.com"},
        ])
        job = self.post_job(payload).get_json()
        self.assertEqual(job["status"], "completed_with_errors")
        self.assertEqual((job["succeeded"], job["failed"]), (2, 1))
        failure = self.client.get(f"/api/jobs/{job['id']}").get_json()["failures"][0]
        self.assertEqual(failure["row_index"], 1)  # tells the client WHICH input row failed
        self.assertIn("Invalid recipient", failure["error"])

    def test_job_where_every_recipient_is_invalid_is_failed_immediately(self):
        runner = self.use_manual_runner()
        job = self.post_job(self.payload(recipients=[{"name": ""}, {"email": "x"}])).get_json()
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["failed"], 2)
        self.assertEqual(runner.submitted, [])  # nothing to process, so nothing queued

    def test_unrenderable_job_field_rejected_upfront(self):
        # event_name affects EVERY certificate, so we fail fast instead of failing them all.
        response = self.post_job(self.payload(event_name="पाइथन कार्यशाला"))
        self.assertEqual(response.status_code, 400)

    def test_unknown_routes_return_json_errors(self):
        response = self.client.get("/api/nope")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"]["code"], "not_found")
