import json, time, urllib.request

BASE = "http://127.0.0.1:5000"

def call(method, path, body=None):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

# 300 generated recipients, plus one invalid one on purpose
many = [{"name": f"Person {i}", "email": f"p{i}@example.com"} for i in range(300)]
many.append({"name": "", "email": "not-an-email"})

job = call("POST", "/api/jobs", {
    "event_name": "Python Backend Bootcamp 2026",
    "issued_by": "Tech Club",
    "recipients": many,
})
print("Created:", job["id"], job["status"])

while job["status"] in ("pending", "processing"):
    time.sleep(0.2)
    job = call("GET", f"/api/jobs/{job['id']}")
    print(job["status"], f'{job["progress_percent"]}%')

print("Failures:", job["failures"])

# Download all successful certificates as a ZIP
urllib.request.urlretrieve(f"{BASE}/api/jobs/{job['id']}/download", "certificates.zip")
print("Saved certificates.zip")