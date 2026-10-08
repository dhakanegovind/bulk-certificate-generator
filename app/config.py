"""Central place for settings. Every value can be overridden with an environment variable."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    # SQLite file that holds jobs + certificate rows.
    DATABASE_PATH = os.environ.get("DATABASE_PATH", str(BASE_DIR / "data" / "certificates.db"))
    # Folder where generated PDFs are written (one sub-folder per job).
    STORAGE_DIR = os.environ.get("STORAGE_DIR", str(BASE_DIR / "storage"))

    # Upper bound on recipients per request. Protects the server from a single huge job.
    MAX_RECIPIENTS = int(os.environ.get("MAX_RECIPIENTS", 1000))
    # Reject request bodies bigger than this (bytes) before we even parse them.
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 5 * 1024 * 1024))

    # Background processing: how many jobs can be generated at the same time.
    WORKER_THREADS = int(os.environ.get("WORKER_THREADS", 2))
    # If True, jobs run inline inside the request (used by most tests; handy for debugging).
    PROCESS_SYNC = os.environ.get("PROCESS_SYNC", "0") == "1"
    # On startup, re-queue jobs that were interrupted by a crash/restart.
    RECOVER_ON_STARTUP = os.environ.get("RECOVER_ON_STARTUP", "1") == "1"

    # Optional TrueType font (e.g. NotoSans) so names in non-Latin scripts can be rendered.
    CERTIFICATE_FONT_PATH = os.environ.get("CERTIFICATE_FONT_PATH") or None
