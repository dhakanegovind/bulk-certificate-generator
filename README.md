# Bulk Certificate Generator

A backend API that accepts **one request containing many recipients**, generates a PDF
certificate for each valid recipient from a single predefined template, tracks progress, and lets
the client retrieve the results individually or as one ZIP.

**Stack:** Python 3.10+, Flask, SQLite (relational, standard-library `sqlite3`), ReportLab (PDF).

---

## 1. Setup

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
```powershell
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

No database server is needed: SQLite creates `data/certificates.db` automatically on first start,
and PDFs are written to `storage/`.

## 2. Run the application

```bash
python run.py          # serves on http://127.0.0.1:5000
```

Optional environment variables (all have defaults, see `app/config.py`):

| Variable | Default | Meaning |
|---|---|---|
| `PORT` / `HOST` | `5000` / `127.0.0.1` | Where to listen |
| `DATABASE_PATH` | `data/certificates.db` | SQLite file |
| `STORAGE_DIR` | `storage/` | Where PDFs are saved |
| `MAX_RECIPIENTS` | `1000` | Max recipients per request |
| `WORKER_THREADS` | `2` | Jobs that can be generated concurrently |
| `PROCESS_SYNC` | `0` | `1` = generate inside the request (debugging) |
| `CERTIFICATE_FONT_PATH` | _(unset)_ | Path to a `.ttf` font for non-Latin names (see "Known limitations") |

## 3. Run the tests

```bash
python -m unittest discover -v     # standard library, nothing extra needed
# or, if you installed pytest:
pytest -v
```

The suite (45 tests) covers: creating a job, input validation (request-level and per-recipient),
PDF generation, job status/progress (including progress observed *mid-run*), failure of a single
certificate, retrieval (single PDF, ZIP, error cases), real background-thread processing, and
crash recovery.

---

## 4. API

Base path: `/api`. All responses are JSON except file downloads. Errors always look like:

```json
{"error": {"code": "validation_error", "message": "The request is invalid.", "details": [...]}}
```

### Submit a certificate generation request

`POST /api/jobs`

| Field | Required | Notes |
|---|---|---|
| `event_name` | yes | e.g. the course/event, max 120 chars |
| `issued_by` | yes | organisation/person, max 80 chars |
| `title` | no | default `"Certificate of Completion"` |
| `issue_date` | no | `YYYY-MM-DD`, default today (UTC) |
| `recipients` | yes | list of `{"name": "...", "email": "..."}`, 1 to `MAX_RECIPIENTS` |

```bash
curl -X POST http://127.0.0.1:5000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
        "event_name": "Python Backend Bootcamp 2026",
        "issued_by": "Tech Club",
        "issue_date": "2026-10-08",
        "recipients": [
          {"name": "Asha Rao",   "email": "asha@example.com"},
          {"name": "Ravi Kumar", "email": "ravi@example.com"},
          {"name": "",           "email": "not-an-email"}
        ]
      }'
```

Response: **`202 Accepted`** (work is queued, not finished) with a `Location` header:

```json
{
  "id": "e155a982e15a4b7ea1096f22ca438b3d",
  "status": "pending",
  "total": 3, "succeeded": 0, "failed": 1, "pending": 2,
  "progress_percent": 33,
  "links": {"self": "/api/jobs/e155...", "certificates": "...", "download_all": "..."}
}
```

### Check progress / result

`GET /api/jobs/<job_id>`

```bash
curl http://127.0.0.1:5000/api/jobs/<job_id>
```

`status` is one of `pending`, `processing`, `completed` (all succeeded),
`completed_with_errors` (some failed), `failed` (all failed / job crashed).
The response also contains a `failures` array: for each failed recipient, its `row_index`
(0-based position in your request), name, email and the reason.

### List certificates of a job

`GET /api/jobs/<job_id>/certificates?status=success|failed|pending&limit=100&offset=0`

Each successful entry includes a `download_url`.

### Retrieve generated certificates

| What | Request |
|---|---|
| One certificate (PDF) | `GET /api/certificates/<certificate_id>/download` |
| Certificate metadata | `GET /api/certificates/<certificate_id>` |
| **All successful certificates (ZIP)** | `GET /api/jobs/<job_id>/download` |

```bash
curl -OJ http://127.0.0.1:5000/api/jobs/<job_id>/download
```

The ZIP is only served when the job has finished (`409` otherwise) and contains only the
successful certificates, named `0001_Asha_Rao.pdf` (request position + name).

### Status codes

`202` job accepted · `200` OK · `400` invalid request · `404` unknown job/certificate ·
`409` not ready / not downloadable · `413` body too large.

---

## 5. How it works

```
 POST /api/jobs ──► validate request ──► INSERT job + 1 row per recipient ──► 202 + job id
                          │ (400 if invalid)        (invalid recipients stored as 'failed')
                          ▼
                 background worker thread: for each 'pending' certificate
                     render PDF ─► save file ─► UPDATE row (success / failed + reason)
                          │
 GET /api/jobs/<id> ◄─────┘  counts are computed from the certificate rows
```

Code layout:

| File | Responsibility |
|---|---|
| `app/__init__.py` | App factory: config, DB init, runner, error handlers, crash recovery |
| `app/routes.py` | HTTP only: parse request, call service, build JSON |
| `app/service.py` | Business logic: create job, process job, query state |
| `app/validation.py` | Pure validation functions |
| `app/certificate.py` | The certificate template (ReportLab) |
| `app/runner.py` | Background thread pool wrapper |
| `app/db.py` | Schema + SQLite connection helper |

Data model: `jobs (1) ──< certificates (many)`. A job has its settings, `status` and `total`;
each certificate row has the recipient, `status` (`pending`/`success`/`failed`), `file_path`
and `error`.

## 6. Important design decisions

**Asynchronous (background) processing, not synchronous.** A request may contain up to 1000
recipients. Generating them inside the HTTP request would make the client wait (seconds to
minutes), risk timeouts from proxies/browsers, and tie up a web worker. Instead `POST /jobs`
validates, saves, and returns `202` immediately; a background thread does the work and the client
polls `GET /jobs/<id>`. I chose an in-process `ThreadPoolExecutor` over Celery/Redis because it
needs zero extra infrastructure and is plenty for this scope. The runner is a small isolated class
(`app/runner.py`), so swapping to a real queue later only changes that file and one call site.

**Failure isolation.** Each certificate is generated inside its own `try/except` and saved in
its own DB transaction. One failure marks that row `failed` with a human-readable reason and the
loop continues. A half-written PDF is never left behind (written to `*.tmp`, then atomically
renamed; deleted on error). The job ends as `completed_with_errors` when some failed.

**Two-level validation.** Problems with the *request itself* (no recipients, missing event
name, too many recipients, bad date) are rejected with `400` and create nothing. Problems with
an *individual recipient* (bad email, empty name) do not reject the request: that recipient is
recorded as a failed certificate with the reason, and everyone else is processed. Invalid rows
are therefore visible in the same `failures` list as generation errors.

**Counts are derived, not stored.** `succeeded/failed/pending` are computed with
`COUNT ... GROUP BY status` over the certificate rows. There is one source of truth, so
counters can't drift after a crash.

**Progress is real.** Each certificate is committed individually and no transaction is held
open while rendering, so `GET /jobs/<id>` shows live progress. SQLite runs in WAL mode so
reads don't block on the worker's writes.

**Crash recovery / idempotency.** The worker only processes certificates still `pending`.
On startup the app re-queues jobs left `pending`/`processing` by a previous run, so a restart
doesn't strand jobs, and already-finished certificates are never regenerated.

**Short-lived DB connections.** SQLite connections can't be shared across threads, so every
request/worker opens its own via the `connect()` context manager (commit on success, rollback on
error, always close).

**Other choices.** IDs are random UUIDs (not guessable sequential numbers; also safe to use in
file paths). Files are stored as `storage/<job_id>/<certificate_id>.pdf` and never use
user-supplied text in paths. The request body is capped at 5 MB, and recipients per request at
`MAX_RECIPIENTS`. Job-level fields that would break *every* certificate (e.g. unrenderable
characters in `event_name`) are rejected up-front rather than producing a job where everything
fails.

## 7. Known limitations (and how I'd address them)

* **Non-Latin names.** ReportLab's built-in fonts only cover Western characters, and it fails
  silently (wrong glyphs) on others, so the app detects this and fails that one certificate
  with a clear message. Set `CERTIFICATE_FONT_PATH` to a TrueType font that covers your scripts
  (e.g. Noto Sans Devanagari) to enable them. With a custom font all text uses that single font.
* **Single-process only.** The thread pool lives inside the web process. Run one process
  (`python run.py`). Several gunicorn workers would each try to resume unfinished jobs on startup.
  For multi-process/multi-server deployment move to Celery/RQ with a Redis broker and
  atomically "claim" jobs.
* **SQLite / local disk.** Fine for one machine. For production: PostgreSQL (swap `app/db.py`, or
  adopt SQLAlchemy) and object storage such as S3 for the PDFs.
* **No authentication, rate limiting or retention policy** (kept out of scope on purpose). The
  ZIP is built in memory, which is fine for the size cap here but would be streamed for bigger jobs.
* **No retry endpoint** for failed certificates; a client would fix the data and submit a new job.
