import io
import zipfile

from tests.base import AppTestCase


class RetrievalTests(AppTestCase):
    def first_cert(self, job_id):
        return self.client.get(f"/api/jobs/{job_id}/certificates").get_json()["certificates"][0]

    def test_download_single_certificate(self):
        job = self.post_job().get_json()
        cert = self.first_cert(job["id"])
        self.assertTrue(cert["download_url"].endswith("/download"))
        with self.client.get(cert["download_url"]) as response:  # `with` closes the file handle
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "application/pdf")
            self.assertTrue(response.data.startswith(b"%PDF"))
            self.assertIn("Alice_Johnson", response.headers["Content-Disposition"])

    def test_certificate_metadata_endpoint(self):
        job = self.post_job().get_json()
        cert = self.first_cert(job["id"])
        body = self.client.get(f"/api/certificates/{cert['id']}").get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["recipient_name"], "Alice Johnson")

    def test_download_all_as_zip(self):
        job = self.post_job().get_json()
        response = self.client.get(f"/api/jobs/{job['id']}/download")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/zip")
        archive = zipfile.ZipFile(io.BytesIO(response.data))
        self.assertEqual(archive.namelist(),
                         ["0001_Alice_Johnson.pdf", "0002_Bob_Smith.pdf", "0003_Carol_White.pdf"])
        self.assertTrue(archive.read("0001_Alice_Johnson.pdf").startswith(b"%PDF"))

    def test_zip_contains_only_successful_certificates(self):
        payload = self.payload(recipients=[
            {"name": "Good Person", "email": "g@b.co"}, {"name": "", "email": "bad"},
        ])
        job = self.post_job(payload).get_json()
        archive = zipfile.ZipFile(io.BytesIO(self.client.get(f"/api/jobs/{job['id']}/download").data))
        self.assertEqual(archive.namelist(), ["0001_Good_Person.pdf"])

    def test_cannot_download_while_job_is_unfinished(self):
        self.use_manual_runner()
        job = self.post_job().get_json()
        response = self.client.get(f"/api/jobs/{job['id']}/download")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "job_not_finished")

    def test_pending_or_failed_certificate_is_not_downloadable(self):
        job = self.post_job(self.payload(recipients=[{"name": "", "email": "bad"}])).get_json()
        cert = self.first_cert(job["id"])
        self.assertNotIn("download_url", cert)  # no link is offered for failed certificates
        response = self.client.get(f"/api/certificates/{cert['id']}/download")
        self.assertEqual(response.status_code, 409)

    def test_job_with_no_successful_certificates_has_nothing_to_zip(self):
        job = self.post_job(self.payload(recipients=[{"name": "", "email": "bad"}])).get_json()
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}/download").status_code, 404)

    def test_unknown_ids_return_404(self):
        self.assertEqual(self.client.get("/api/certificates/nope").status_code, 404)
        self.assertEqual(self.client.get("/api/certificates/nope/download").status_code, 404)
        self.assertEqual(self.client.get("/api/jobs/nope/download").status_code, 404)

    def test_certificate_ids_are_unguessable_uuids_not_paths(self):
        # path-traversal attempt must not escape the storage folder
        self.assertEqual(self.client.get("/api/certificates/..%2F..%2Fetc%2Fpasswd/download").status_code, 404)
