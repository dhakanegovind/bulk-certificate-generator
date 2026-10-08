"""Application factory: builds and configures the Flask app.

Using a factory function (instead of one global `app`) lets tests create a fresh, isolated
app with a temporary database and folder every time.
"""
import logging
import os
from pathlib import Path

from flask import Flask

from .config import Config
from .db import init_db
from .routes import bp, error_response
from .runner import JobRunner
from . import service


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    font_path = app.config["CERTIFICATE_FONT_PATH"]
    if font_path and not os.path.isfile(font_path):
        raise RuntimeError(f"CERTIFICATE_FONT_PATH does not exist: {font_path}")

    Path(app.config["STORAGE_DIR"]).mkdir(parents=True, exist_ok=True)
    init_db(app.config["DATABASE_PATH"])

    runner = JobRunner(workers=app.config["WORKER_THREADS"], sync=app.config["PROCESS_SYNC"])
    app.extensions["job_runner"] = runner
    app.register_blueprint(bp)

    # JSON errors instead of Flask's default HTML pages, so API clients get a consistent format.
    @app.errorhandler(404)
    def _not_found(_):
        return error_response(404, "not_found", "The requested URL was not found.")

    @app.errorhandler(405)
    def _method_not_allowed(_):
        return error_response(405, "method_not_allowed", "Method not allowed for this URL.")

    @app.errorhandler(413)
    def _too_large(_):
        return error_response(413, "payload_too_large", "Request body is too large.")

    # Crash recovery: pick up jobs that were running when the server last stopped.
    if app.config["RECOVER_ON_STARTUP"]:
        for job_id in service.recover_unfinished_jobs(app.config["DATABASE_PATH"]):
            app.logger.info("Resuming unfinished job %s", job_id)
            runner.submit(service.process_job, app.config["DATABASE_PATH"],
                          app.config["STORAGE_DIR"], job_id, font_path)

    return app
