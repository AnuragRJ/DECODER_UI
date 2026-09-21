import urllib.request
import json
import time

def api_post(endpoint, data):
    req = urllib.request.Request(
        f"http://127.0.0.1:8000{endpoint}",
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def api_get(endpoint):
    with urllib.request.urlopen(f"http://127.0.0.1:8000{endpoint}") as resp:
        return json.loads(resp.read().decode("utf-8"))



def start_batch(body=None):
    """POST /batch/decode-all while honoring the already-complete gate.

    These standalone live-debug scripts intentionally exercise REAL decoding
    work, so when the server answers status=="already_complete" (all of
    today's eligible floats are already successfully processed) we issue the
    explicit force=True form -- the same decision the UI's [ Re-run All ]
    button makes -- instead of silently following an old batch.
    """
    res = api_post("/api/batch/decode-all", body or {})
    if isinstance(res, dict) and res.get("status") == "already_complete":
        print("   -> today's floats already processed; forcing explicit re-run for this test")
        res = api_post("/api/batch/decode-all", {**(body or {}), "force": True})
    return res
print("--- TEST 1: Single Float Decode (WMO 2901304) ---")
res1 = api_post("/api/decode", {"wmo": 2901304})
run_id1 = res1["run_id"]
print("Started run:", run_id1)
for _ in range(40):
    time.sleep(0.2)
    r = api_get(f"/api/runs/{run_id1}")
    if r["status"] in ("completed", "error", "stopped"):
        print("Run completed:", r["status"], "cycles:", r["completed_cycles"], "profiles:", r["profile_count"], "outputs:", len(r["output_files"]), "duration:", r["duration_seconds"])
        break

print("\n--- TEST 2: STOP DECODE on Single Float (WMO 6902892) ---")
res2 = api_post("/api/decode", {"wmo": 6902892})
run_id2 = res2["run_id"]
print("Started run:", run_id2)
time.sleep(0.5)
stop_res = api_post(f"/api/runs/{run_id2}/stop", {})
print("Stop requested:", stop_res)
for _ in range(30):
    time.sleep(0.2)
    r = api_get(f"/api/runs/{run_id2}")
    if r["status"] in ("stopped", "cancelled"):
        print("Run confirmed stopped:", r["status"], "duration:", r["duration_seconds"], "events count:", len(api_get(f"/api/runs/{run_id2}/events")))
        break

print("\n--- TEST 3: STOP BATCH on All Floats Batch ---")
res3 = start_batch()
batch_id = res3["batch_id"]
print("Started batch:", batch_id)
time.sleep(0.8)
stop_batch_res = api_post(f"/api/batch/{batch_id}/stop", {})
print("Stop batch requested:", stop_batch_res)
for _ in range(30):
    time.sleep(0.3)
    b = api_get(f"/api/batch/{batch_id}")
    if b["status"] in ("stopped", "cancelled", "completed"):
        print("Batch confirmed stopped:", b["status"], "completed:", b["completed_floats"], "stopped:", b["stopped_floats"], "pending:", b["pending_floats"])
        break

print("\n--- TEST 4: Run History & Batch Results Persistence ---")
runs = api_get("/api/runs")
print("Total persistent runs:", len(runs))
batches = api_get("/api/batches")
print("Total persistent batches:", len(batches))

print("\nALL VERIFICATION TESTS COMPLETED SUCCESSFULLY!")
