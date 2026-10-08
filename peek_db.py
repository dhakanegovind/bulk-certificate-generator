import sqlite3

conn = sqlite3.connect("data/certificates.db")
conn.row_factory = sqlite3.Row

print("--- JOBS ---")
for row in conn.execute("SELECT id, status, total, created_at, completed_at FROM jobs"):
    print(dict(row))

print("\n--- FAILED CERTIFICATES ---")
for row in conn.execute(
    "SELECT job_id, row_index, recipient_name, recipient_email, error "
    "FROM certificates WHERE status = 'failed'"
):
    print(dict(row))

print("\n--- COUNTS PER JOB ---")
for row in conn.execute(
    "SELECT job_id, status, COUNT(*) AS n FROM certificates GROUP BY job_id, status"
):
    print(dict(row))