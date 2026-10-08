"""HTTP layer: parse the request, call the service, shape the JSON response. No business logic."""
import io
import re
import zipfile
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file, url_for

from . import service
from .certificate import is_renderable
from .db import connect
from .validation import ValidationError, validate_job_request

bp = Blueprint("api", __name__, url_prefix="/api")

VALID_CERT_STATUSES = ("pending", "success", "failed")


def error_response(status_code, code, message, details=None):
    body = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return jsonify(body), status_code


def _db_path():
    return current_app.config["DATABASE_PATH"]


def _job_links(job_id):
    return {
        "self": url_for("api.get_job", job_id=job_id),
        "certificates": url_for("api.list_job_certificates", job_id=job_id),
        "download_all": url_for("api.download_job_zip", job_id=job_id),
    }


def _certificate_json(cert):
    data = {
        "id": cert["id"],
        "row_index": cert["row_index"],
        "recipient_name": cert["recipient_name"],
        "recipient_email": cert["recipient_email"],
        "status": cert["status"],
        "error": cert["error"],
    }
    if cert["status"] == "success":
        data["download_url"] = url_for("api.download_certificate", cert_id=cert["id"])
    return data


def _slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "_", text or "").strip("_")[:40] or "certificate"


# --------------------------------------------------------------------------- create a job
@bp.post("/jobs")
def create_job():
    payload = request.get_json(silent=True)  # None if the body is missing / not valid JSON
    font_path = current_app.config["CERTIFICATE_FONT_PATH"]
    try:
        job_fields, recipients = validate_job_request(
            payload,
            current_app.config["MAX_RECIPIENTS"],
            is_renderable=lambda text: is_renderable(text, font_path),
        )
    except ValidationError as exc:
        return error_response(400, "validation_error", "The request is invalid.", exc.details)

    with connect(_db_path()) as conn:
        job_id = service.create_job(conn, job_fields, recipients)
    # ^ the `with` block has COMMITTED here. Only now is it safe to hand the job to a worker,
    #   otherwise the worker could look for rows that are not visible yet.

    with connect(_db_path()) as conn:
        needs_processing = service.get_job(conn, job_id)["status"] == "pending"
    if needs_processing:
        current_app.extensions["job_runner"].submit(
            service.process_job, _db_path(), current_app.config["STORAGE_DIR"], job_id, font_path
        )

    with connect(_db_path()) as conn:
        job = service.get_job(conn, job_id)
    job["links"] = _job_links(job_id)
    response = jsonify(job)
    response.status_code = 202  # Accepted: work was queued, not necessarily finished
    response.headers["Location"] = job["links"]["self"]
    return response


# --------------------------------------------------------------------------- job status
@bp.get("/jobs/<job_id>")
def get_job(job_id):
    with connect(_db_path()) as conn:
        job = service.get_job(conn, job_id)
        if job is None:
            return error_response(404, "not_found", "Job not found.")
        job["failures"] = service.get_failures(conn, job_id)
    job["links"] = _job_links(job_id)
    return jsonify(job)


@bp.get("/jobs/<job_id>/certificates")
def list_job_certificates(job_id):
    status = request.args.get("status")
    if status is not None and status not in VALID_CERT_STATUSES:
        return error_response(400, "validation_error",
                              f"status must be one of: {', '.join(VALID_CERT_STATUSES)}.")
    try:
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
        if not (1 <= limit <= 500) or offset < 0:
            raise ValueError
    except ValueError:
        return error_response(400, "validation_error",
                              "limit must be 1-500 and offset must be 0 or more (integers).")

    with connect(_db_path()) as conn:
        if service.get_job(conn, job_id) is None:
            return error_response(404, "not_found", "Job not found.")
        certs = service.list_certificates(conn, job_id, status, limit, offset)
        total = service.count_certificates(conn, job_id, status)
    return jsonify({
        "total": total, "limit": limit, "offset": offset,
        "certificates": [_certificate_json(c) for c in certs],
    })


# --------------------------------------------------------------------------- retrieval
@bp.get("/certificates/<cert_id>")
def get_certificate(cert_id):
    with connect(_db_path()) as conn:
        cert = service.get_certificate(conn, cert_id)
    if cert is None:
        return error_response(404, "not_found", "Certificate not found.")
    return jsonify(_certificate_json(cert))


@bp.get("/certificates/<cert_id>/download")
def download_certificate(cert_id):
    with connect(_db_path()) as conn:
        cert = service.get_certificate(conn, cert_id)
    if cert is None:
        return error_response(404, "not_found", "Certificate not found.")
    if cert["status"] != "success":
        # 409 Conflict: the resource exists but is not in a state where it can be downloaded.
        return error_response(409, "not_available",
                              f"Certificate is not available (status: {cert['status']}).")
    path = Path(current_app.config["STORAGE_DIR"]) / cert["file_path"]
    if not path.is_file():
        return error_response(404, "file_missing", "The certificate file is missing on the server.")
    return send_file(path, mimetype="application/pdf", as_attachment=True,
                     download_name=f"{_slug(cert['recipient_name'])}_certificate.pdf")


@bp.get("/jobs/<job_id>/download")
def download_job_zip(job_id):
    with connect(_db_path()) as conn:
        job = service.get_job(conn, job_id)
        if job is None:
            return error_response(404, "not_found", "Job not found.")
        if job["status"] in service.IN_PROGRESS:
            return error_response(409, "job_not_finished",
                                  f"Job is still {job['status']}. Try again when it has finished.")
        certs = service.successful_certificates(conn, job_id)
    if not certs:
        return error_response(404, "no_certificates", "No certificates were generated for this job.")

    storage = Path(current_app.config["STORAGE_DIR"])
    buffer = io.BytesIO()  # built in memory: fine for <= MAX_RECIPIENTS small PDFs
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for cert in certs:
            path = storage / cert["file_path"]
            if path.is_file():
                # row number prefix guarantees unique names even if two people share a name
                archive.write(path, f"{cert['row_index'] + 1:04d}_{_slug(cert['recipient_name'])}.pdf")
    buffer.seek(0)
    return send_file(buffer, mimetype="application/zip", as_attachment=True,
                     download_name=f"certificates_{job_id}.zip")
