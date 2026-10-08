import os
import unittest
from pathlib import Path

from app.certificate import (TextTooLongError, UnsupportedCharactersError, is_renderable,
                             render_certificate)
from tests.base import AppTestCase

KWARGS = dict(title="Certificate of Completion", event_name="Python Bootcamp",
              issued_by="Tech Club", issue_date="2026-10-08", certificate_id="abc123")


class RendererUnitTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "cert.pdf"

    def test_creates_a_real_pdf(self):
        render_certificate(self.out, recipient_name="Asha Rao", **KWARGS)
        self.assertTrue(self.out.read_bytes().startswith(b"%PDF"))
        self.assertGreater(self.out.stat().st_size, 1000)

    def test_accented_latin_names_work(self):
        render_certificate(self.out, recipient_name="José Müller", **KWARGS)
        self.assertTrue(self.out.exists())

    def test_long_realistic_name_is_shrunk_to_fit(self):
        name = "Alexandrina Maria Fernanda de la Cruz y Montenegro-Villanueva"
        render_certificate(self.out, recipient_name=name, **KWARGS)
        self.assertTrue(self.out.exists())

    def test_unsupported_script_raises_clear_error_and_leaves_no_file(self):
        with self.assertRaises(UnsupportedCharactersError):
            render_certificate(self.out, recipient_name="गोविंद", **KWARGS)
        self.assertFalse(self.out.exists())
        self.assertEqual(os.listdir(self.tmp.name), [])  # no .tmp leftovers either

    def test_impossibly_long_name_raises(self):
        with self.assertRaises(TextTooLongError):
            render_certificate(self.out, recipient_name="W" * 100, **KWARGS)
        self.assertFalse(self.out.exists())

    def test_is_renderable(self):
        self.assertTrue(is_renderable("José"))
        self.assertFalse(is_renderable("गोविंद"))
        self.assertTrue(is_renderable("गोविंद", font_path="/some/font.ttf"))


class GenerationThroughApiTests(AppTestCase):
    def test_generation_writes_one_pdf_per_recipient(self):
        job = self.post_job().get_json()
        self.assertEqual(job["status"], "completed")
        certs = self.client.get(f"/api/jobs/{job['id']}/certificates").get_json()["certificates"]
        storage = Path(self.config["STORAGE_DIR"])
        files = sorted(p.name for p in (storage / job["id"]).glob("*.pdf"))
        self.assertEqual(files, sorted(f"{c['id']}.pdf" for c in certs))
        for pdf in (storage / job["id"]).glob("*.pdf"):
            self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))

    def test_job_larger_than_a_handful_completes(self):
        names = [f"Person{i} Test" for i in range(60)]
        job = self.post_job(self.payload(names)).get_json()
        self.assertEqual((job["total"], job["succeeded"], job["failed"]), (60, 60, 0))
